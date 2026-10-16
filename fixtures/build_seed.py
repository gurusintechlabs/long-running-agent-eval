#!/usr/bin/env python3
"""Deterministically build the seed repo: python build_seed.py TARGET_DIR

Copies fixtures/seed_export_service/ into TARGET_DIR as a fresh git repo with
one commit (fixed identity and dates) and prints the commit SHA.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "seed_export_service"
DATE = "2026-01-01T00:00:00Z"
IDENT = {
    "GIT_AUTHOR_NAME": "LRAE Seed",
    "GIT_AUTHOR_EMAIL": "seed@lrae.invalid",
    "GIT_COMMITTER_NAME": "LRAE Seed",
    "GIT_COMMITTER_EMAIL": "seed@lrae.invalid",
    "GIT_AUTHOR_DATE": DATE,
    "GIT_COMMITTER_DATE": DATE,
}
MESSAGE = "Seed: items service"
IGNORE = shutil.ignore_patterns(
    "__pycache__", ".pytest_cache", "*.pyc", ".venv", ".git", ".DS_Store"
)


def _git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(IDENT)
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True,
        capture_output=True, text=True,
    )
    return out.stdout.strip()


def build(target: Path) -> str:
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"target not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, target, ignore=IGNORE, dirs_exist_ok=True)
    # Normalise modes so the tree hash is independent of the checkout umask.
    for p in target.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            p.chmod(0o644)
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "core.autocrlf", "false")
    _git(target, "config", "core.filemode", "false")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "--no-gpg-sign", "-m", MESSAGE)
    return _git(target, "rev-parse", "HEAD")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: build_seed.py TARGET_DIR", file=sys.stderr)
        return 2
    print(build(Path(argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
