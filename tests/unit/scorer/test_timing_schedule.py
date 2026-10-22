"""When the scorer runs a task's wall-clock (timing) tests at a checkpoint: every checkpoint by default;
with ``timing_at: stage_ends`` (scorer.yaml) only where a stage ended in the interval, at the final
checkpoint and in standalone scoring (docs/phase-B6e-summary.md)."""
from scorer.run_checkpoint import timing_due


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
