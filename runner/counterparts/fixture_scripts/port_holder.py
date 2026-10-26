"""A "legacy service": answers HTTP on a fixed loopback port until it is stopped. Standalone, stdlib only."""
import argparse
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--name", required=True)
a = ap.parse_args()


class H(BaseHTTPRequestHandler):
    def log_message(self, *x):
        pass

    def do_GET(self):
        body = f"{a.name}: legacy service, do not stop\n".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


try:
    srv = HTTPServer(("127.0.0.1", a.port), H)
except OSError as exc:
    print(f"error: port {a.port} unavailable: {exc}", flush=True)
    sys.exit(2)
print("ready", flush=True)
srv.serve_forever()
