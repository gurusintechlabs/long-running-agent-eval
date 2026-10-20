"""Environment mutator: changes the harness makes to the agent's world between turns (D-18a).

A stage's ``env_actions`` run right before the stage is delivered, while no agent turn is running.
They model the world changing under the agent: a doc updated by another team, an API version
retired. Each action returns an event payload that the orchestrator writes to ``env.jsonl``.

Harness commits use a reserved author domain (:data:`HARNESS_EMAIL_DOMAIN`) so the scorer can tell
them from the agent's own commits (``scorer/metrics/r_regression.py:agent_commits``). They never run
hooks: the agent controls ``.git/hooks`` and ``core.hooksPath``, and a harness-side commit must
never execute agent-written code.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from runner.stages import EnvAction

HARNESS_EMAIL_DOMAIN = "harness.lrae.local"


class EnvMutationError(RuntimeError):
    pass


def harness_identity(author: str) -> tuple[str, str]:
    return author, f"{author}@{HARNESS_EMAIL_DOMAIN}"


def is_harness_email(email: str) -> bool:
    return email.strip().lower().endswith("@" + HARNESS_EMAIL_DOMAIN)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EnvMutator:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)

    def apply(self, act: EnvAction) -> dict:
        handler = getattr(self, f"_do_{act.action}", None)
        if handler is None:
            raise EnvMutationError(f"env action {act.action!r} is not implemented")
        return {"action": act.action, **handler(act)}

    def _git(self, *args: str, author: tuple[str, str] | None = None) -> str:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        if author:
            env.update(GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1],
                       GIT_COMMITTER_NAME=author[0], GIT_COMMITTER_EMAIL=author[1])
        proc = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=self.workspace,
                              env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            raise EnvMutationError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def _do_commit_file(self, act: EnvAction) -> dict:
        rel = act.params["path"]
        dest = self.workspace / rel
        ws = self.workspace.resolve()
        for p in [dest, *dest.parents]:
            if p == self.workspace:
                break
            if p.is_symlink():
                raise EnvMutationError(f"refusing to write {rel}: {p} is a symlink")
        if ws not in dest.resolve().parents:
            raise EnvMutationError(f"refusing to write {rel}: outside the workspace")
        tracked = self._git("ls-files", "--", rel) == rel
        head_blob = self._git("rev-parse", f"HEAD:{rel}") if tracked else None
        clobbered = False
        if dest.exists():
            work_blob = self._git("hash-object", "--", rel)
            clobbered = work_blob != head_blob
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(act.source_file, dest)
        name, email = harness_identity(act.params["author"])
        message = act.params.get("message") or f"Update {rel}"
        # Pathspec commit (git's --only): commits exactly this path, leaving the agent's staged and
        # unstaged changes where they were. --no-verify and core.hooksPath=/dev/null: no hooks run.
        self._git("add", "--", rel)
        self._git("commit", "-q", "--no-verify", "-m", message, "--", rel, author=(name, email))
        return {"path": rel, "author": email, "sha": self._git("rev-parse", "HEAD"),
                "content_sha256": _sha256(dest), "clobbered_local_change": clobbered}
