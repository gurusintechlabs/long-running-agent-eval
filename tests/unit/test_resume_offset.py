import json

from runner.orchestrator import resume_offset_s


def write(path, *events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events))


def ckpt(k, t_s):
    return {"type": "checkpoint", "payload": {"k": k, "t_s": t_s}}


def test_a_checkpoint_on_schedule_resumes_at_its_own_time(tmp_path):
    p = tmp_path / "orchestrator.jsonl"
    write(p, ckpt(1, 1800.2), ckpt(2, 3618.4))
    assert resume_offset_s(p, 2, 1800) == 3618.4


def test_an_early_checkpoint_resumes_at_its_own_time_not_k_intervals(tmp_path):
    """jira-re r02: checkpoint 3 was taken at the interruption, 64.2 min; the clock jumped to 90 min."""
    p = tmp_path / "orchestrator.jsonl"
    write(p, ckpt(2, 3618.4), {"type": "state", "payload": {}}, ckpt(3, 3854.7))
    assert resume_offset_s(p, 3, 1800) == 3854.7


def test_a_checkpoint_taken_again_after_a_resume_uses_the_latest(tmp_path):
    p = tmp_path / "orchestrator.jsonl"
    write(p, ckpt(9, 16286.0), ckpt(10, 18050.0), ckpt(10, 18001.0))
    assert resume_offset_s(p, 10, 1800) == 18001.0


def test_without_a_recorded_checkpoint_falls_back_to_k_intervals(tmp_path):
    p = tmp_path / "orchestrator.jsonl"
    write(p, ckpt(1, 1800.0))
    p.write_text(p.read_text() + "not json\n")
    assert resume_offset_s(p, 2, 1800) == 3600
    assert resume_offset_s(tmp_path / "missing.jsonl", 2, 1800) == 3600
