"""U3: checkpoint diff from mirror.git and scorer log. The repository content is treated as hostile."""
from __future__ import annotations

import os
import subprocess

import pytest

from tests.unit.analysis.synth import make_run
from tests.unit.ui_server.u3_synth import make_mirror, set_checkpoint_shas, snapshot_tree
from ui_server import gitview


@pytest.fixture
def repo_run(runs_dir, tmp_path):
    rid = make_run(runs_dir, n_cp=3)
    rd = runs_dir / rid
    shas = make_mirror(rd, tmp_path, [
        {"msg": "seed", "files": {"a.py": "x = 1\n", "README.md": "hi\n"}},
        {"msg": "add b", "files": {"b.py": "y = 2\n"}},
        {"msg": "change a\n\n<script>alert(1)</script>", "files": {"a.py": "x = 2\nz = 3\n"}},
        {"msg": "binary", "files": {"blob.bin": b"\x00\x01\x02\xff" * 100, "weird \u001b[31mname.txt": "x\n"}},
    ])
    # checkpoint 1 -> seed commit, 2 -> third, 3 -> fourth
    set_checkpoint_shas(rd, {1: shas[0], 2: shas[2], 3: shas[3]})
    return rid, rd, shas


def diff(client, rid, k, **params):
    return client.get(f"/api/runs/{rid}/checkpoints/{k}/diff", params=params)


def test_diff_against_previous_checkpoint(client, repo_run):
    rid, _rd, shas = repo_run
    b = diff(client, rid, 2).json()
    assert b["available"] and b["base_kind"] == "previous_checkpoint" and b["base"] == shas[0] and b["head"] == shas[2]
    assert [c["sha"] for c in b["commits"]] == [shas[2], shas[1]]          # newest first
    assert b["commits"][0]["subject"] == "change a" and b["commits"][0]["author"] == "t"
    assert {f["path"]: (f["added"], f["deleted"]) for f in b["files"]} == {"a.py": (2, 1), "b.py": (1, 0)}
    assert "+z = 3" in b["diff"] and "-x = 1" in b["diff"] and b["diff_truncated"] is False


def test_first_checkpoint_has_a_root_diff(client, repo_run):
    rid, _rd, shas = repo_run
    b = diff(client, rid, 1).json()
    assert b["available"] and b["base_kind"] == "root" and b["base"] is None
    assert [c["sha"] for c in b["commits"]] == [shas[0]]
    assert "+x = 1" in b["diff"]


def test_explicit_base_and_validation(client, repo_run):
    rid, _rd, shas = repo_run
    b = diff(client, rid, 3, base=shas[1]).json()
    assert b["base_kind"] == "param" and b["base"] == shas[1]
    assert {f["path"] for f in b["files"]} >= {"a.py", "blob.bin"}
    for bad in ("HEAD", "main", "--output=/tmp/x", shas[1][:10], shas[1].upper(), shas[1] + "a", "-p", "a" * 41,
                shas[1] + ";id", "../../x", ""):
        assert diff(client, rid, 3, base=bad).status_code == 400, bad
    assert diff(client, rid, 3, base="0" * 40).status_code == 404


def test_binary_and_control_characters_are_safe(client, repo_run):
    rid, _rd, _s = repo_run
    r = diff(client, rid, 3)
    b = r.json()
    assert r.status_code == 200 and b["available"]
    bin_ = next(f for f in b["files"] if f["path"] == "blob.bin")
    assert bin_["binary"] is True and bin_["added"] is None
    assert "Binary files" in b["diff"] and "\x00" not in b["diff"]
    assert any("name.txt" in f["path"] for f in b["files"])


def test_hostile_commit_message_is_plain_data(client, repo_run):
    rid, _rd, _s = repo_run
    b = diff(client, rid, 2).json()
    assert all("<script>" not in c["subject"] for c in b["commits"])     # only the subject line is returned
    assert r_ct(client, rid).startswith("application/json")


def r_ct(client, rid):
    return diff(client, rid, 2).headers["content-type"]


def test_diff_size_cap(client, runs_dir, tmp_path):
    rid = make_run(runs_dir, n_cp=2)
    rd = runs_dir / rid
    shas = make_mirror(rd, tmp_path, [{"msg": "s", "files": {"a": "1\n"}},
                                      {"msg": "big", "files": {"big.txt": "line of text\n" * 300_000}}])
    set_checkpoint_shas(rd, {1: shas[0], 2: shas[1]})
    b = diff(client, rid, 2, max_bytes=5000).json()
    assert b["diff_truncated"] is True and len(b["diff"]) <= 5000
    b = diff(client, rid, 2, max_bytes=10**9).json()
    assert len(b["diff"].encode()) <= gitview.MAX_DIFF_BYTES and b["diff_truncated"] is True


def test_unknown_checkpoint_and_missing_mirror(client, repo_run, runs_dir):
    rid, _rd, _s = repo_run
    assert diff(client, rid, 99).status_code == 404
    assert client.get(f"/api/runs/{rid}/checkpoints/abc/diff").status_code == 422
    plain = make_run(runs_dir, n_cp=1, repeat=7)
    b = diff(client, plain, 1).json()
    assert b["available"] is False and "mirror" in b["reason"]


def test_head_not_in_mirror(client, repo_run):
    rid, rd, shas = repo_run
    set_checkpoint_shas(rd, {2: "f" * 40})
    b = diff(client, rid, 2).json()
    assert b["available"] is False and "not in mirror" in b["reason"]


def test_hostile_repo_config_is_not_executed(client, repo_run, tmp_path):
    """A repo whose own config/attributes try to run commands must not get to run them."""
    rid, rd, _s = repo_run
    marker = tmp_path / "pwned"
    cfg = rd / "mirror.git" / "config"
    cfg.write_text(cfg.read_text() + f"""
[diff]
	external = touch {marker}
[core]
	fsmonitor = touch {marker}
	pager = touch {marker}
	hooksPath = {tmp_path}/hooks
[diff "evil"]
	textconv = touch {marker}
	command = touch {marker}
""")
    (rd / "mirror.git" / "info").mkdir(exist_ok=True)
    (rd / "mirror.git" / "info" / "attributes").write_text("*.py diff=evil\n")
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "reference-transaction").write_text(f"#!/bin/sh\ntouch {marker}\n")
    os.chmod(hooks / "reference-transaction", 0o755)
    r = diff(client, rid, 2)
    assert r.status_code == 200 and r.json()["available"] is True
    assert "+z = 3" in r.json()["diff"]
    assert not marker.exists()


def test_git_is_run_without_a_shell_and_with_a_scrubbed_env(client, repo_run, monkeypatch):
    rid, _rd, _s = repo_run
    calls = []
    real = subprocess.Popen

    def spy(cmd, *a, **kw):
        calls.append((cmd, kw))
        return real(cmd, *a, **kw)
    monkeypatch.setattr(subprocess, "Popen", spy)
    monkeypatch.setenv("SECRET_TOKEN_FOR_TEST", "s3cret")
    assert diff(client, rid, 2).status_code == 200
    assert calls
    for cmd, kw in calls:
        assert isinstance(cmd, list) and kw.get("shell") is False
        assert "SECRET_TOKEN_FOR_TEST" not in kw["env"] and kw["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
        for flag in ("core.hooksPath=/dev/null", "protocol.ext.allow=never", "--no-pager"):
            assert flag in cmd
        assert cmd[0].endswith("git")
    assert any("--no-ext-diff" in c for c, _ in calls)


def test_mirror_symlink_out_of_run_dir_is_ignored(client, runs_dir, tmp_path):
    rid = make_run(runs_dir, n_cp=1, repeat=5)
    other = tmp_path / "elsewhere"
    other.mkdir()
    shas = make_mirror(other, tmp_path / "w", [{"msg": "s", "files": {"a": "1\n"}}])
    os.symlink(other / "mirror.git", runs_dir / rid / "mirror.git")
    set_checkpoint_shas(runs_dir / rid, {1: shas[0]})
    b = diff(client, rid, 1).json()
    assert b["available"] is False


def test_valid_sha_helper():
    assert gitview.valid_sha("a" * 40) and not gitview.valid_sha("A" * 40) and not gitview.valid_sha("a" * 39 + "\n")
    assert not gitview.valid_sha(None) and not gitview.valid_sha("g" * 40)


def test_diff_writes_nothing(client, repo_run, runs_dir):
    rid, _rd, _s = repo_run
    before = snapshot_tree(runs_dir)
    diff(client, rid, 2)
    diff(client, rid, 3)
    assert snapshot_tree(runs_dir) == before


# ------------------------------------------------------------------------------------- scorer log

def test_scorer_log_tail_and_cap(client, runs_dir):
    rid = make_run(runs_dir, n_cp=2)
    sd = runs_dir / rid / "scorer"
    sd.mkdir()
    (sd / "score-t1.log").write_text("hello\nworld \x1b[31mred\x00\n")
    b = client.get(f"/api/runs/{rid}/checkpoints/1/scorer-log").json()
    assert b["truncated"] is False and b["text"].startswith("hello") and "\x00" not in b["text"]
    (sd / "score-t2.log").write_text("HEAD\n" + "x" * 50_000 + "\nTAIL\n")
    b = client.get(f"/api/runs/{rid}/checkpoints/2/scorer-log", params={"max_bytes": 1000}).json()
    assert b["truncated"] is True and b["size"] > 50_000 and b["text"].rstrip().endswith("TAIL") and "HEAD" not in b["text"]
    assert client.get(f"/api/runs/{rid}/checkpoints/3/scorer-log").status_code == 404
    assert client.get(f"/api/runs/{rid}/checkpoints/0/scorer-log").status_code == 404
    assert client.get(f"/api/runs/{rid}/checkpoints/1/scorer-log", params={"max_bytes": 10**9}).status_code == 422


def test_scorer_log_symlink_escape(client, runs_dir, tmp_path):
    rid = make_run(runs_dir, n_cp=1)
    sd = runs_dir / rid / "scorer"
    sd.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    os.symlink(secret, sd / "score-t1.log")
    assert client.get(f"/api/runs/{rid}/checkpoints/1/scorer-log").status_code == 404


def test_scorer_log_path_params_cannot_traverse(client, runs_dir):
    rid = make_run(runs_dir, n_cp=1)
    (runs_dir / rid / "scorer").mkdir()
    for k in ("..%2F..%2Fmanifest", "1%2F..%2F1", "-1", "1.5", "1e3"):
        assert client.get(f"/api/runs/{rid}/checkpoints/{k}/scorer-log").status_code in (404, 422), k
