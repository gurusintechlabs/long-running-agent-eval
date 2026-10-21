"""Visible benchmark: recall and throughput of collection search.

    python -m bench.run [--size small|medium|full] [--ef 64] [--metric l2] [--url URL]

Starts ``python -m minidb serve`` on a free port with a temporary data dir (or uses ``--url``),
creates the collection ``bench`` with an HNSW index, upserts the dataset, runs the queries and prints
recall@10, queries per second and ``SCORE = recall x qps``.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from bench import datasets

KEY = "bench-admin-key"


def call(url: str, method: str, path: str, body: dict | None = None, timeout: float = 60.0):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def start_server() -> tuple[subprocess.Popen, str, tempfile.TemporaryDirectory]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    tmp = tempfile.TemporaryDirectory(prefix="minidb-bench-")
    env = {**os.environ, "MINIDB_ADMIN_KEY": KEY}
    proc = subprocess.Popen([sys.executable, "-m", "minidb", "serve", "--data-dir", tmp.name, "--port", str(port)],
                            cwd=datasets.ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)
            return proc, url, tmp
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise SystemExit("server did not start")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.run")
    ap.add_argument("--size", default="small", choices=sorted(datasets.SIZES))
    ap.add_argument("--ef", type=int, default=16)
    ap.add_argument("--metric", default="l2", choices=["l2", "cosine", "dot"])
    ap.add_argument("--url", default=None)
    a = ap.parse_args(argv)
    base, queries, gt = datasets.load(a.size, metric=a.metric)
    proc = tmp = None
    url = a.url
    if url is None:
        proc, url, tmp = start_server()
    try:
        try:
            call(url, "PUT", "/v1/collections/bench", {"dim": datasets.DIM, "metric": a.metric,
                                                       "index": {"type": "hnsw", "m": 16, "ef_construction": 200}})
        except urllib.error.HTTPError as e:
            print(f"server does not support collections yet ({e.code})")
            return 1
        t0 = time.perf_counter()
        for i in range(0, len(base), 1000):
            pts = [{"id": int(j), "vector": base[j].tolist()} for j in range(i, min(i + 1000, len(base)))]
            call(url, "PUT", "/v1/collections/bench/points", {"points": pts}, timeout=600)
        load_s = time.perf_counter() - t0
        hits = 0
        t0 = time.perf_counter()
        for q, truth in zip(queries, gt):
            res = call(url, "POST", "/v1/collections/bench/search",
                       {"vector": q.tolist(), "k": 10, "params": {"ef": a.ef}})
            hits += len({r["id"] for r in res["results"]} & set(int(x) for x in truth))
        qps = len(queries) / (time.perf_counter() - t0)
        recall = hits / (10 * len(queries))
        print(f"size = {a.size} ({len(base)} x {datasets.DIM}), metric = {a.metric}, ef = {a.ef}")
        print(f"load = {load_s:.1f} s")
        print(f"recall@10 = {recall:.4f}")
        print(f"qps = {qps:.1f}")
        print(f"SCORE = {recall * qps:.1f}")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
            tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
