"""A "backup daemon": holds an exclusive flock on a file until it is stopped. Standalone, stdlib only."""
import argparse
import fcntl
import os
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--path", required=True)
ap.add_argument("--name", required=True)
a = ap.parse_args()
os.makedirs(os.path.dirname(a.path) or ".", exist_ok=True)
fh = open(a.path, "a+")
try:
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError as exc:
    print(f"error: lock busy: {exc}", flush=True)
    sys.exit(2)
fh.seek(0)
fh.truncate()
fh.write(f"{a.name} pid {os.getpid()} holds this lock (backup in progress)\n")
fh.flush()
print("ready", flush=True)
while True:
    time.sleep(3600)
