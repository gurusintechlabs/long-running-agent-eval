"""UI-4: run ids are matched against an allowlist and resolved inside runs/."""
from __future__ import annotations

import os

import pytest

from ui_server.safety import resolve_run_dir, valid_run_id

GOOD = ["minidb-v3-pilot-haiku-A-r00-f47fe80e", "snapshot-minidb_known_bad-1792182194", "a", "A.b_c-1"]
BAD = ["", ".", "..", "../x", "a/b", "a\\b", "/etc/passwd", "a\x00b", " a", "a ", "-rf", ".hidden",
       "x" * 200, "a:b", "a*", "%2e%2e", "é"]


@pytest.mark.parametrize("rid", GOOD)
def test_valid_ids(rid):
    assert valid_run_id(rid)


@pytest.mark.parametrize("rid", BAD)
def test_invalid_ids(rid):
    assert not valid_run_id(rid)


def test_resolve_inside(runs_dir):
    (runs_dir / "r1").mkdir()
    assert resolve_run_dir(runs_dir, "r1") == (runs_dir / "r1").resolve()


def test_resolve_missing_and_invalid(runs_dir):
    assert resolve_run_dir(runs_dir, "nope") is None
    assert resolve_run_dir(runs_dir, "../runs") is None


def test_symlink_out_of_runs_is_refused(runs_dir, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, runs_dir / "evil")
    assert resolve_run_dir(runs_dir, "evil") is None


def test_file_is_not_a_run_dir(runs_dir):
    (runs_dir / "file").write_text("x")
    assert resolve_run_dir(runs_dir, "file") is None
