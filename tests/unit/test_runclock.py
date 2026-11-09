"""Run time from wall time across resumes (telemetry/runclock.py).

The orchestrator emits ``run.clock`` ``{start_epoch, offset_s}`` on entering RUNNING, where ``start_epoch``
is already the virtual origin (wall start minus ``offset_s``). So a segment really starts at
``start_epoch + offset_s``, and an event in it is at run time ``epoch - start_epoch``.
"""
import pytest

from telemetry.runclock import RunClock, run_time

S0 = 1_000_000.0          # first start, offset 0
R1 = S0 + 9_000.0          # resumed at this wall time from a checkpoint at run time 3600
S1 = R1 - 3_600.0


def two_segments() -> RunClock:
    return RunClock([(S0, 0.0), (S1, 3_600.0)])


def test_single_segment_is_wall_time_minus_start():
    c = RunClock([(S0, 0.0)])
    assert c.t_s(S0 + 125.0) == 125.0
    assert c.origin == S0


def test_after_a_resume_run_time_continues_from_the_offset():
    c = two_segments()
    assert c.t_s(R1) == pytest.approx(3_600.0)
    assert c.t_s(R1 + 60.0) == pytest.approx(3_660.0)


def test_before_a_resume_uses_the_first_segment():
    c = two_segments()
    assert c.t_s(S0 + 1_000.0) == pytest.approx(1_000.0)


def test_work_discarded_by_a_resume_is_placed_at_the_resume_point():
    c = two_segments()
    # wall time S0 + 5000 is run time 5000 of the first segment, beyond the checkpoint (3600) it resumed from
    assert c.t_s(S0 + 5_000.0) == pytest.approx(3_600.0)


def test_marks_are_ordered_by_real_start_not_by_virtual_origin():
    # the second origin (S1) is earlier than the first segment's late events; order must not depend on it
    c = RunClock([(S1, 3_600.0), (S0, 0.0)])
    assert c.t_s(S0 + 1_000.0) == pytest.approx(1_000.0)
    assert c.t_s(R1 + 10.0) == pytest.approx(3_610.0)
    assert c.origin == S1


def test_before_the_first_start_is_measured_from_it():
    assert two_segments().t_s(S0 - 5.0) == pytest.approx(-5.0)


def test_from_events_reads_run_clock_events_only():
    evs = [{"type": "state", "payload": {}},
           {"type": "run.clock", "payload": {"start_epoch": S0, "offset_s": 0.0}},
           {"type": "run.clock", "payload": {"start_epoch": S1, "offset_s": 3_600.0}},
           {"type": "run.clock", "payload": {"start_epoch": "bad"}}]
    c = RunClock.from_events(evs)
    assert c.marks == [(S0, 0.0), (S1, 3_600.0)]
    assert not RunClock.from_events([])


def test_run_time_accepts_a_plain_origin_or_a_clock():
    assert run_time(S0, S0 + 7.0) == 7.0
    assert run_time(two_segments(), R1 + 7.0) == pytest.approx(3_607.0)
