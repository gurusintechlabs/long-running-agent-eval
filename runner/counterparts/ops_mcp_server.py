"""Stdio MCP server for the ops channel. Standalone, stdlib only: it is copied next to the run's work
dir and started by the Claude Code CLI (``--mcp-config``) with ``LRAE_OPS_URL`` in its environment.
It forwards tool listing and calls to the harness's ops service over loopback HTTP.

JSON-RPC 2.0, one message per line: ``initialize``, ``notifications/*``, ``ping``, ``tools/list``,
``tools/call``.
"""
import json
import os
import sys
import urllib.request

URL = os.environ.get("LRAE_OPS_URL", "")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback only, never a proxy


def _http(method, path, body=None):
    req = urllib.request.Request(URL + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-LRAE-Source": "mcp"})
    with _OPENER.open(req, timeout=30) as r:
        return json.loads(r.read())


def _handle(msg):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ops", "version": "1"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": _http("GET", "/tools")["tools"]}
    if method == "tools/call":
        try:
            out = _http("POST", "/call", {"tool": params.get("name"), "arguments": params.get("arguments") or {}})
        except OSError as exc:
            out = {"text": f"ops channel unavailable: {exc}", "is_error": True}
        return {"content": [{"type": "text", "text": out["text"]}], "isError": bool(out["is_error"])}
    raise LookupError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:  # a notification: no reply
            continue
        try:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": _handle(msg)}
        except LookupError:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found"}}
        except Exception as exc:  # noqa: BLE001 - never crash the session's MCP server
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(exc)}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
