import json
import os
import subprocess
from pathlib import Path

import pytest

from scorer.metrics.w_repeat import repeat_work, repeated_tool_calls


def git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@e"}
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repo, files, msg="c"):
    for rel, text in files.items():
        p = repo / rel
        if text is None:
            p.unlink()
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            p.write_bytes(text)
        else:
            p.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def lines(*xs):
    return "".join(f"{x}\n" for x in xs)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    return r


def test_known_churn(repo):
    seed = commit(repo, {"a.py": lines(*[f"seed{i}" for i in range(10)])})
    c1 = commit(repo, {"b.py": lines(*[f"own{i}" for i in range(8)])})
    # interval (c1, c2]: delete 4 own lines (b.py), delete 2 seed lines (a.py), add 6 lines
    c2 = commit(repo, {
        "b.py": lines("own0", "own1", "own2", "own3", "new0", "new1"),
        "a.py": lines(*[f"seed{i}" for i in range(2, 10)]),
    })
    r = repeat_work(repo, seed, c1, c2)
    assert r["lines_added"] == 2
    assert r["lines_deleted_own"] == 4
    assert r["W"] == pytest.approx(2.0)
    assert r["detail"]["lines_deleted_total"] == 6


def test_first_interval_vs_seed_has_no_own_lines(repo):
    seed = commit(repo, {"a.py": lines("x", "y", "z")})
    c1 = commit(repo, {"a.py": lines("x", "q", "z", "w")})
    r = repeat_work(repo, seed, seed, c1)
    assert r["lines_deleted_own"] == 0 and r["W"] == 0.0 and r["lines_added"] == 2


def test_no_added_lines_gives_zero(repo):
    seed = commit(repo, {"a.py": "x\n"})
    c1 = commit(repo, {"a.py": lines("x", "y", "z")})
    c2 = commit(repo, {"a.py": lines("x")})
    r = repeat_work(repo, seed, c1, c2)
    assert r["lines_added"] == 0 and r["W"] == 0.0 and r["lines_deleted_own"] == 2


def test_rename_is_not_churn(repo):
    seed = commit(repo, {"s.py": "s\n"})
    body = lines(*[f"line{i}" for i in range(20)])
    c1 = commit(repo, {"old.py": body})
    git(repo, "mv", "old.py", "new.py")
    c2 = commit(repo, {"new.py": body + "extra\n"})
    r = repeat_work(repo, seed, c1, c2)
    assert r["lines_added"] == 1 and r["lines_deleted_own"] == 0 and r["W"] == 0.0


def test_deleted_own_file_counts(repo):
    seed = commit(repo, {"s.py": "s\n"})
    c1 = commit(repo, {"tmp.py": lines("a", "b", "c")})
    c2 = commit(repo, {"tmp.py": None, "n.py": lines("a2")})
    r = repeat_work(repo, seed, c1, c2)
    assert r["lines_deleted_own"] == 3 and r["lines_added"] == 1 and r["W"] == pytest.approx(3.0)


def test_binary_files_ignored(repo):
    seed = commit(repo, {"s.py": "s\n"})
    c1 = commit(repo, {"img.bin": b"\x00\x01\x02" * 50, "t.py": lines("a")})
    c2 = commit(repo, {"img.bin": b"\x00\x09" * 90, "t.py": lines("b")})
    r = repeat_work(repo, seed, c1, c2)
    assert r["lines_added"] == 1 and r["lines_deleted_own"] == 1 and r["W"] == 1.0


def test_works_on_bare_repo(repo, tmp_path):
    seed = commit(repo, {"s.py": "s\n"})
    c1 = commit(repo, {"b.py": lines("a", "b")})
    c2 = commit(repo, {"b.py": lines("a", "c")})
    bare = tmp_path / "m.git"
    git(tmp_path, "clone", "-q", "--bare", str(repo), str(bare))
    r = repeat_work(bare, seed, c1, c2)
    assert r["lines_deleted_own"] == 1 and r["lines_added"] == 1 and r["W"] == 1.0


# ---- repeated tool calls

def write_events(path: Path, events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events) + "not json\n")


def call(mono, tool, inp, typ="tool.call"):
    return {"type": typ, "mono_ns": mono, "payload": {"tool": tool, "input": inp,
                                                       "tool_use_id": str(mono)}}


def test_repeated_tool_calls(tmp_path):
    f = tmp_path / "agent_stream.jsonl"
    write_events(f, [
        call(5, "Read", {"file_path": "a.py"}),             # before window
        call(11, "Read", {"file_path": "a.py"}),
        call(12, "Read", {"file_path": "a.py"}),            # repeat 1
        call(13, "Bash", {"command": "ls", "x": 1}),
        call(14, "Bash", {"x": 1, "command": "ls"}),        # repeat 2 (key order irrelevant)
        call(15, "Bash", {"command": "pwd"}),
        call(16, "Read", {"file_path": "a.py"}, typ="stream.assistant"),   # not a tool.call
        call(20, "Read", {"file_path": "a.py"}),            # repeat 3 (end inclusive)
        call(21, "Read", {"file_path": "a.py"}),            # after window
    ])
    assert repeated_tool_calls(f, 10, 20) == 3
    assert repeated_tool_calls(f, 0, 100) == 5
    assert repeated_tool_calls(f, 30, 40) == 0


def test_repeated_tool_calls_same_input_different_tool_not_repeat(tmp_path):
    f = tmp_path / "e.jsonl"
    write_events(f, [call(1, "Read", {"p": 1}), call(2, "Grep", {"p": 1})])
    assert repeated_tool_calls(f, 0, 10) == 0
