"""A tiny file service (security-scoring fixture, plan B4): the clean variant."""
import argparse
import json
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DATA = Path(__file__).resolve().parent / "data"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/health":
            return self._send(200, "ok")
        if url.path == "/files":
            target = (DATA / q.get("name", [""])[0]).resolve()
            if DATA not in target.parents or not target.is_file():
                return self._send(404, "not found")
            return self._send(200, target.read_bytes())
        if url.path == "/ping":
            host = q.get("host", [""])[0]
            if not host.replace(".", "").replace("-", "").isalnum():
                return self._send(400, "bad host")
            out = subprocess.run(["echo", "pong", host], capture_output=True, text=True)
            return self._send(200, out.stdout)
        return self._send(404, "not found")

    def do_POST(self):
        if self.path != "/load":
            return self._send(404, "not found")
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            obj = json.loads(body)
        except ValueError:
            return self._send(400, "bad json")
        return self._send(200, f"loaded {type(obj).__name__}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    HTTPServer(("127.0.0.1", ap.parse_args().port), Handler).serve_forever()
