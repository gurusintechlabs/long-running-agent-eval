from pathlib import Path

import pytest

from runner import memory


def test_encode_matches_cli_convention():
    # observed on this machine: underscores and slashes both become '-'
    p = "/Users/tonylee/Documents/coding/longhorizon_testing"
    assert memory.encode_project_path(p) == "-Users-tonylee-Documents-coding-longhorizon-testing"
    assert memory.encode_project_path("/a/b.c/d_e") == "-a-b-c-d-e"


def test_state_dir_path(tmp_path):
    ws = tmp_path / "work" / "run1" / "workspace"
    sd = memory.state_dir(ws, claude_home=tmp_path / "claude")
    assert sd.parent == tmp_path / "claude" / "projects"
    assert sd.name == memory.encode_project_path(ws.resolve())


def test_assert_empty_ok_when_absent_or_empty(tmp_path):
    sd = tmp_path / "x"
    memory.assert_empty(sd)
    sd.mkdir()
    memory.assert_empty(sd)


def test_assert_empty_fails_when_populated(tmp_path):
    sd = tmp_path / "x"
    sd.mkdir()
    (sd / "old.jsonl").write_text("{}")
    with pytest.raises(memory.MemoryError_):
        memory.assert_empty(sd)


def test_snapshot_restore_delete_roundtrip(tmp_path):
    sd = tmp_path / "state"
    (sd / "memory").mkdir(parents=True)
    (sd / "s1.jsonl").write_text("line\n")
    (sd / "memory" / "note.md").write_text("hi")
    snap = tmp_path / "snap"
    memory.snapshot_state(sd, snap)
    memory.delete_state(sd)
    assert not sd.exists()
    memory.restore_state(snap, sd)
    assert (sd / "s1.jsonl").read_text() == "line\n"
    assert (sd / "memory" / "note.md").read_text() == "hi"


def test_snapshot_of_absent_state_dir_is_empty_marker(tmp_path):
    snap = tmp_path / "snap"
    memory.snapshot_state(tmp_path / "nope", snap)
    assert snap.is_dir() and not any(snap.iterdir())


def test_delete_absent_is_noop(tmp_path):
    memory.delete_state(tmp_path / "nope")


def test_check_clean_ancestors(tmp_path):
    ws = tmp_path / "a" / "b" / "workspace"
    ws.mkdir(parents=True)
    memory.check_ancestors(ws, home=tmp_path / "home", stop_at=tmp_path)  # clean
    (tmp_path / "a" / "CLAUDE.md").write_text("x")
    with pytest.raises(memory.MemoryError_, match="CLAUDE.md"):
        memory.check_ancestors(ws, home=tmp_path / "home", stop_at=tmp_path)


def test_check_ancestors_claude_dir_allowed_in_home_only(tmp_path):
    home = tmp_path / "home"
    ws = home / "lrae-work" / "r" / "workspace"
    ws.mkdir(parents=True)
    (home / ".claude").mkdir()
    memory.check_ancestors(ws, home=home, stop_at=tmp_path)  # ~/.claude is fine
    (home / "lrae-work" / ".claude").mkdir()
    with pytest.raises(memory.MemoryError_, match=r"\.claude"):
        memory.check_ancestors(ws, home=home, stop_at=tmp_path)


def test_check_ancestors_flags_claude_md_in_home_itself(tmp_path):
    home = tmp_path / "home"
    ws = home / "w" / "workspace"
    ws.mkdir(parents=True)
    (home / "CLAUDE.md").write_text("x")
    with pytest.raises(memory.MemoryError_):
        memory.check_ancestors(ws, home=home, stop_at=tmp_path)


def test_check_seed_clean(tmp_path):
    memory.check_seed_checkout(tmp_path)
    (tmp_path / ".claude").mkdir()
    with pytest.raises(memory.MemoryError_):
        memory.check_seed_checkout(tmp_path)


def test_check_seed_flags_nested_claude_md(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "CLAUDE.md").write_text("x")
    with pytest.raises(memory.MemoryError_):
        memory.check_seed_checkout(tmp_path)


class TestUserMemoryGuard:
    def make_home(self, tmp_path):
        ch = tmp_path / "claude"
        (ch / "rules").mkdir(parents=True)
        (ch / "CLAUDE.md").write_bytes(b"user memory\n")
        (ch / "rules" / "r.md").write_text("rule")
        return ch

    def test_noop_when_nothing_to_hide(self, tmp_path):
        ch = tmp_path / "claude"
        ch.mkdir()
        g = memory.UserMemoryGuard(ch, lock=tmp_path / "lock")
        assert g.engage() == []
        g.restore()

    def test_moves_aside_and_restores_byte_identical(self, tmp_path):
        ch = self.make_home(tmp_path)
        g = memory.UserMemoryGuard(ch, lock=tmp_path / "lock")
        moved = g.engage()
        assert set(moved) == {"CLAUDE.md", "rules"}
        assert not (ch / "CLAUDE.md").exists() and not (ch / "rules").exists()
        g.restore()
        assert (ch / "CLAUDE.md").read_bytes() == b"user memory\n"
        assert (ch / "rules" / "r.md").read_text() == "rule"
        assert not (tmp_path / "lock").exists()

    def test_recover_after_crash(self, tmp_path):
        ch = self.make_home(tmp_path)
        lock = tmp_path / "lock"
        memory.UserMemoryGuard(ch, lock=lock).engage()  # "crash": never restored
        assert memory.UserMemoryGuard.recover(ch, lock) is True
        assert (ch / "CLAUDE.md").read_bytes() == b"user memory\n"
        assert memory.UserMemoryGuard.recover(ch, lock) is False  # idempotent

    def test_second_engage_refused_while_locked(self, tmp_path):
        ch = self.make_home(tmp_path)
        lock = tmp_path / "lock"
        memory.UserMemoryGuard(ch, lock=lock).engage()
        with pytest.raises(memory.MemoryError_, match="lock"):
            memory.UserMemoryGuard(ch, lock=lock).engage()

    def test_context_manager_restores_on_exception(self, tmp_path):
        ch = self.make_home(tmp_path)
        with pytest.raises(RuntimeError):
            with memory.UserMemoryGuard(ch, lock=tmp_path / "lock"):
                raise RuntimeError("boom")
        assert (ch / "CLAUDE.md").exists()


def test_clean_removes_only_listed_workspaces(tmp_path):
    ch = tmp_path / "claude"
    ws_a, ws_b = tmp_path / "w" / "a" / "workspace", tmp_path / "w" / "b" / "workspace"
    other = ch / "projects" / "-some-other-project"
    other.mkdir(parents=True)
    (other / "keep.jsonl").write_text("x")
    for ws in (ws_a, ws_b):
        ws.mkdir(parents=True)
        sd = memory.state_dir(ws, ch)
        sd.mkdir(parents=True)
        (sd / "s.jsonl").write_text("x")
    removed = memory.clean_workspaces([ws_a], claude_home=ch)
    assert len(removed) == 1
    assert not memory.state_dir(ws_a, ch).exists()
    assert memory.state_dir(ws_b, ch).exists()
    assert (other / "keep.jsonl").exists()
