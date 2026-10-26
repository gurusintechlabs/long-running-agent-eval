"""When the scorer runs a task's wall-clock (timing) tests at a checkpoint: every checkpoint by default;
with ``timing_at: stage_ends`` (scorer.yaml) only where a stage ended in the interval, at the final
checkpoint and in standalone scoring (docs/phase-B6e-summary.md)."""
from scorer.metrics import r_regression as rr
from scorer.run_checkpoint import last_known_hidden, timing_due


def delivered(stage, t):
    return {"type": "stage.delivered", "payload": {"stage": stage, "t_s": t}}


ORCH = [delivered(0, 0.0), delivered(1, 700.0), {"type": "run.done", "payload": {"t_s": 2500.0}}]


def test_every_checkpoint_by_default():
    assert timing_due({}, {}, ORCH, 0.0, 600.0)
    assert timing_due({"timing_at": "checkpoints"}, {}, ORCH, 0.0, 600.0)


def test_stage_ends_only():
    cfg = {"timing_at": "stage_ends"}
    assert not timing_due(cfg, {}, ORCH, 0.0, 600.0)          # stage 0 still running
    assert timing_due(cfg, {}, ORCH, 600.0, 1200.0)           # stage 0 ended at 700 (stage 1 delivered)
    assert not timing_due(cfg, {}, ORCH, 1200.0, 1800.0)
    assert timing_due(cfg, {}, ORCH, 1800.0, 2400.0 + 600)    # run.done: the last stage ended
    assert timing_due(cfg, {"final": "kill"}, ORCH, 1200.0, 1800.0)   # any final checkpoint
    assert timing_due(cfg, {"standalone": True}, [], 0.0, 600.0)


def test_unknown_schedules_are_rejected(tmp_path):
    import pytest

    from scorer.metrics import p_hidden
    (tmp_path / "scorer.yaml").write_text("timing_at: sometimes\n")
    with pytest.raises(ValueError):
        p_hidden.load_config(tmp_path)


# R across checkpoints that did not run the timing tests (minidb v3 blind build: every deselected timing test
# was counted as a regression)

def _pass(k, outcomes, timing, ok=True, pid=None):
    pid = pid or f"p{k}"
    return [{"type": "scorer.start", "payload": {"k": k, "pass_id": pid}},
            {"type": "scorer.metric", "payload": {"k": k, "pass_id": pid, "name": "P",
                                                  "detail": {"outcomes": outcomes, "timing": timing}}},
            {"type": "scorer.done", "payload": {"k": k, "pass_id": pid, "ok": ok}}]


def test_a_test_that_was_not_run_now_is_not_a_regression():
    prev = {"a": "passed", "t_timing": "passed"}
    assert rr.count_regressions(prev, {"a": "passed"}, missing_ok=True) == []
    assert rr.count_regressions(prev, {"a": "passed"}) == ["t_timing"]      # the regression suite: deleted
    r = rr.score_regressions(prev, {"a": "passed"}, {"r": "passed"}, {}, hidden_partial=True)
    assert r["value"] == 1.0 and r["detail"]["regressed_regression"] == ["r"]


def test_last_known_hidden_fills_tests_a_checkpoint_did_not_run():
    events = (_pass(1, {"a": "passed", "t_timing": "passed"}, True)
              + _pass(2, {"a": "failed", "t_timing": "failed"}, True, ok=False)      # a failed pass: ignored
              + _pass(2, {"a": "passed"}, False, pid="p2b")
              + _pass(3, {"a": "failed", "b": "passed"}, False))
    assert last_known_hidden(events, 3) == {"a": "failed", "b": "passed", "t_timing": "passed"}
    assert last_known_hidden(events, 2) == {"a": "passed", "t_timing": "passed"}
    assert last_known_hidden(events, 0) is None


def test_a_timing_failure_is_compared_with_the_last_checkpoint_that_ran_it():
    events = _pass(1, {"t_timing": "passed"}, True) + _pass(2, {}, False)
    prev = last_known_hidden(events, 2)
    assert rr.count_regressions(prev, {}, missing_ok=True) == []                       # k=3, deselected
    assert rr.count_regressions(prev, {"t_timing": "failed"}, missing_ok=True) == ["t_timing"]  # k=3, ran
