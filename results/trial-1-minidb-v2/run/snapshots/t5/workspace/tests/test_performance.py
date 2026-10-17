"""Sections 13, 15 and 16: every operation of the performance tables stays within its limit,
measured through ``python -m minidb`` exactly as a client sees it (see benchmarks/bench.py)."""
from benchmarks import bench


def test_performance_limits_in_memory(capsys):
    status = bench.main()
    report = capsys.readouterr().out
    assert status == 0, report


def test_performance_limits_with_a_database_file(capsys, tmp_path):
    status = bench.main(str(tmp_path))
    report = capsys.readouterr().out
    assert status == 0, report
