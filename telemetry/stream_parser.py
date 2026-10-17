"""Parse Claude Code ``stream-json`` messages into parsed events (docs/interfaces.md §2).

``parse_message`` is pure and total: an unknown or malformed message yields no events and never
raises, because the runner pump must not die on a CLI shape it has not seen.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

TEXT_LIMIT = 20_000
RESULT_TEXT_LIMIT = 2_000
TEXT_TAIL_LIMIT = 2_000


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _truncate_strings(obj: Any) -> tuple[Any, bool]:
    """Copy of ``obj`` with every string longer than TEXT_LIMIT cut; flag whether any was."""
    if isinstance(obj, str):
        return (obj[:TEXT_LIMIT], True) if len(obj) > TEXT_LIMIT else (obj, False)
    if isinstance(obj, dict):
        out, hit = {}, False
        for k, v in obj.items():
            out[k], h = _truncate_strings(v)
            hit = hit or h
        return out, hit
    if isinstance(obj, list):
        items = [_truncate_strings(v) for v in obj]
        return [i[0] for i in items], any(i[1] for i in items)
    return obj, False


def _text_event(sid, text: str) -> tuple[str, dict]:
    return "assistant.text", {"session_id": sid, "text": text[:TEXT_LIMIT], "text_sha256": _sha256(text),
                              "truncated": len(text) > TEXT_LIMIT}


def _tool_call_event(sid, block: dict) -> tuple[str, dict]:
    raw = block.get("input")
    inp, truncated = _truncate_strings(raw if raw is not None else {})
    payload = {"session_id": sid, "tool_use_id": block.get("id"), "tool": block.get("name"), "input": inp}
    if truncated:
        payload["input_sha256"] = _sha256(_canonical(raw))
        payload["truncated"] = True
    return "tool.call", payload


def _content_size(content: Any) -> int:
    """Characters of text in a ``tool_result`` content (a string or a list of blocks)."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(_content_size(b.get("text") if isinstance(b, dict) else b) for b in content)
    return 0


def _content_text(content: Any) -> str:
    """Concatenated text of a ``tool_result`` content (a string or a list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_content_text(b.get("text") if isinstance(b, dict) else b) for b in content)
    return ""


# One pytest summary line, with or without "=====" rules: "== 2 failed, 5 passed, 1 skipped in 1.2s ==",
# "3 passed in 0.12s (0:00:00)", "1 error in 0.3s", "no tests ran in 0.01s".
_COUNT = r"\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?|rerun)"
_SUMMARY = re.compile(
    rf"^[=\s]*(?P<body>(?:{_COUNT})(?:\s*,\s*(?:{_COUNT}))*|no tests ran)"
    r"(?:\s+in\s+[\d.]+s(?:\s*\([\d:.]+\))?)?[=\s]*$")
_ONE = re.compile(r"(\d+) (passed|failed|errors?|skipped)")


def parse_pytest_summary(text: str) -> dict | None:
    """Counts from the last pytest summary line in ``text`` (None if there is none).

    ``xfailed``/``xpassed``/``deselected``/``warnings`` are recognised but not counted."""
    found = None
    for line in text.splitlines():
        m = _SUMMARY.match(line.strip())
        if m:
            found = (m.group("body"), line.strip().strip("=").strip())
    if found is None:
        return None
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for n, word in _ONE.findall(found[0]):
        counts["errors" if word.startswith("error") else word] += int(n)
    return {**counts, "raw_summary": found[1]}


def _blocks(msg: dict) -> list[dict]:
    content = (msg.get("message") or {}).get("content")
    if isinstance(content, str):  # a plain-string user/assistant message
        return [{"type": "text", "text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def _parse_assistant(msg: dict) -> list[tuple[str, dict]]:
    sid, out = msg.get("session_id"), []
    for b in _blocks(msg):
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            out.append(_text_event(sid, b["text"]))
        elif b.get("type") == "tool_use":
            out.append(_tool_call_event(sid, b))
    return out


def _parse_user(msg: dict) -> list[tuple[str, dict]]:
    sid, out = msg.get("session_id"), []
    for b in _blocks(msg):
        if b.get("type") != "tool_result":
            continue
        text = _content_text(b.get("content"))
        out.append(("tool.result", {"session_id": sid, "tool_use_id": b.get("tool_use_id"),
                                    "is_error": bool(b.get("is_error")),
                                    "size": _content_size(b.get("content")),
                                    "text_tail": text[-TEXT_TAIL_LIMIT:]}))
        summary = parse_pytest_summary(text)
        if summary:
            out.append(("agent.test_run", {"session_id": sid, "tool_use_id": b.get("tool_use_id"), **summary}))
    return out


def _parse_system(msg: dict) -> list[tuple[str, dict]]:
    sub, sid = msg.get("subtype"), msg.get("session_id")
    if sub == "init":
        return [("session.init", {"session_id": sid, "model": msg.get("model"), "tools": msg.get("tools"),
                                  "mcp_servers": msg.get("mcp_servers"),
                                  "permissionMode": msg.get("permissionMode"),
                                  "apiKeySource": msg.get("apiKeySource")})]
    if sub == "compact_boundary":
        meta = msg.get("compact_metadata") or msg.get("compactMetadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        return [("context.compaction", {"session_id": sid, "trigger": meta.get("trigger", msg.get("trigger")),
                                        "pre_tokens": meta.get("pre_tokens", msg.get("pre_tokens"))})]
    return []


def _parse_result(msg: dict) -> list[tuple[str, dict]]:
    payload = {"session_id": msg.get("session_id"), "subtype": msg.get("subtype"),
               "is_error": bool(msg.get("is_error")), "total_cost_usd": msg.get("total_cost_usd"),
               "num_turns": msg.get("num_turns"), "usage": msg.get("usage"),
               "modelUsage": msg.get("modelUsage")}
    if payload["is_error"]:
        payload["result_text"] = str(msg.get("result") or "")[:RESULT_TEXT_LIMIT]
    return [("session.result", payload)]


_PARSERS = {"assistant": _parse_assistant, "user": _parse_user, "system": _parse_system,
            "result": _parse_result}


def parse_message(msg: dict) -> list[tuple[str, dict]]:
    """Parsed ``(type, payload)`` events for one stream-json message; ``[]`` for unknown shapes."""
    try:
        parser = _PARSERS.get(msg.get("type")) if isinstance(msg, dict) else None
        return parser(msg) if parser else []
    except Exception:  # noqa: BLE001 - the pump must survive any CLI shape
        return []
