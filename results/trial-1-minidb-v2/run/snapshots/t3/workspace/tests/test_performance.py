"""Section 13: every operation of the performance table stays within its limit, measured
through ``python -m minidb`` exactly as a client sees it (see benchmarks/bench.py)."""
from benchmarks import bench


def test_performance_limits(capsys):
    status = bench.main()
    report = capsys.readouterr().out
    assert status == 0, report
