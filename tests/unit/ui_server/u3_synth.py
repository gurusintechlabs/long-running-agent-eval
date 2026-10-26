"""Helpers that add U3-relevant event files and git mirrors to synthetic runs."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.unit.analysis.synth import START, iso


def line(run_id: str, source: str, typ: str, seq: int, payload: dict, t_s: float, mono: int | None = None) -> str:
    """One envelope line in the exact compact form the real EventWriter produces."""
    return json.dumps({"ts": iso(t_s), "mono_ns": mono if mono is not None else int(t_s * 1e9), "run_id": run_id,
                       "source": source, "type": typ, "seq": seq, "payload": payload},
                      separators=(",", ":"), ensure_ascii=False)


def write_lines(path: Path, lines: list[str], *, torn: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n" if lines else ""
    if torn is not None:
        text += torn          # no trailing newline: a line still being written
    path.write_text(text, encoding="utf-8")


def append(path: Path, text: str) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def agent_stream(run_dir: Path, rid: str, script: list[tuple], *, torn: str | None = None) -> list[str]:
    """``script``: ``(t_s, kind, ...)`` tuples written as parsed events, each tool/result preceded by the raw
    ``stream.assistant`` / ``stream.user`` copy like the real pump does.

    kinds: ``("text", t, text)``, ``("tool", t, id, name, input, result_text, is_error)``,
    ``("compaction", t, pre_tokens)``, ``("test_run", t, passed, failed)``."""
    out, seq = [], 0

    def add(typ, payload, t):
        nonlocal seq
        out.append(line(rid, "agent_stream", typ, seq, payload, t))
        seq += 1

    add("session.init", {"session_id": "s1", "model": "m", "tools": []}, 0.5)
    for it in script:
        kind, t = it[0], it[1]
        if kind == "text":
            add("stream.assistant", {"type": "assistant"}, t)
            add("assistant.text", {"session_id": "s1", "text": it[2], "text_sha256": "x", "truncated": False}, t)
        elif kind == "tool":
            _k, t, tid, name, inp, res, err = it
            add("stream.assistant", {"type": "assistant"}, t)
            add("tool.call", {"session_id": "s1", "tool_use_id": tid, "tool": name, "input": inp}, t)
            add("stream.user", {"type": "user", "message": {"role": "user", "content": [
                {"tool_use_id": tid, "type": "tool_result", "content": [{"type": "text", "text": res}]}]}}, t + 0.5)
            add("tool.result", {"session_id": "s1", "tool_use_id": tid, "is_error": err, "size": len(res),
                                "text_tail": res[-2000:]}, t + 0.5)
        elif kind == "compaction":
            add("context.compaction", {"session_id": "s1", "trigger": "auto", "pre_tokens": it[2]}, t)
        elif kind == "test_run":
            add("agent.test_run", {"session_id": "s1", "tool_use_id": "u", "passed": it[2], "failed": it[3],
                                   "errors": 0, "skipped": 0, "raw_summary": f"{it[3]} failed, {it[2]} passed"}, t)
    write_lines(run_dir / "events" / "agent_stream.jsonl", out, torn=torn)
    return out


def guardrail(run_dir: Path, rid: str, evs: list[tuple]) -> None:
    """``evs``: ``(t_s, type, payload)``."""
    write_lines(run_dir / "events" / "guardrail.jsonl",
                [line(rid, "guardrail", typ, i, p, t) for i, (t, typ, p) in enumerate(evs)])


def add_orch(run_dir: Path, rid: str, evs: list[tuple]) -> None:
    """Append ``(t_s, type, payload)`` events to orchestrator.jsonl (seq continues)."""
    p = run_dir / "events" / "orchestrator.jsonl"
    n = len(p.read_text().splitlines())
    append(p, "".join(line(rid, "orchestrator", typ, n + i, pl, t) + "\n" for i, (t, typ, pl) in enumerate(evs)))


def set_checkpoint_shas(run_dir: Path, shas: dict[int, str]) -> None:
    p = run_dir / "events" / "orchestrator.jsonl"
    out = []
    for ln in p.read_text().splitlines():
        e = json.loads(ln)
        if e["type"] == "checkpoint" and e["payload"]["k"] in shas:
            e["payload"]["head_sha"] = shas[e["payload"]["k"]]
        out.append(json.dumps(e))
    p.write_text("\n".join(out) + "\n")


def snapshot_tree(root: Path) -> dict:
    """{relative path: (size, mtime_ns)} of every file, for no-write assertions."""
    out = {}
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = Path(dp) / f
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
    return out


GIT_ENV = {"PATH": os.environ.get("PATH", ""), "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
           "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True, text=True).stdout.strip()


def make_mirror(run_dir: Path, tmp: Path, commits: list[dict]) -> list[str]:
    """Build ``run_dir/mirror.git`` from ``commits`` = [{"msg":..., "files": {path: str|bytes}}] (cumulative);
    returns the commit shas."""
    work = tmp / "work"
    work.mkdir(parents=True, exist_ok=True)
    _git(work, "init", "-q", "-b", "main")
    shas = []
    for c in commits:
        for path, content in c["files"].items():
            f = work / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(content if isinstance(content, bytes) else content.encode())
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", c["msg"])
        shas.append(_git(work, "rev-parse", "HEAD"))
    _git(work, "clone", "-q", "--bare", str(work), str(run_dir / "mirror.git"))
    return shas


__all__ = ["START", "line", "write_lines", "append", "agent_stream", "guardrail", "add_orch",
           "set_checkpoint_shas", "snapshot_tree", "make_mirror"]
