import io
import json

import pytest

from runner import watch

START = 1_800_000_000.0


def ts(t):
    from datetime import UTC, datetime
    return datetime.fromtimestamp(START + t, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def write(art, source, events):
    p = art / "events" / f"{source}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as fh:
        for i, (t, typ, payload) in enumerate(events):
            fh.write(json.dumps({"ts": ts(t), "type": typ, "seq": i, "payload": payload}) + "\n")


@pytest.fixture
def art(tmp_path):
    art = tmp_path / "runs" / "exp-A-r00-abcd"
    art.mkdir(parents=True)
    (art / "manifest.json").write_text(json.dumps({"run_id": art.name, "start_epoch": START, "config": "A",
                                                   "spec": {"task": {"id": "t"}}, "model": "m"}))
    write(art, "orchestrator", [(0, "run.clock", {"start_epoch": START}),
                                (0, "stage.delivered", {"stage": 0, "t_s": 0.0}),
                                (300, "turn.end", {"turn": 1, "returncode": 0}),
                                (300, "stage.delivered", {"stage": 1, "t_s": 300.0, "kind": "change_request"}),
                                (600, "checkpoint", {"k": 1, "t_s": 600.0, "cumulative_cost_usd": 1.5})])
    write(art, "agent_stream", [(299, "assistant.text", {"text": "Stage 0 is done."})])
    write(art, "scorer", [(610, "scorer.metric", {"k": 1, "pass_id": "p", "name": "P", "value": 0.5,
                                                  "detail": {"passed": 5, "active": 10}}),
                          (610, "scorer.metric", {"k": 1, "pass_id": "p", "name": "R", "value": 0.0}),
                          (611, "scorer.hazard", {"k": 1, "dimension": "context", "t_detected_s": 600.0,
                                                  "evidence": "1 constraint violation"}),
                          (612, "scorer.done", {"k": 1, "pass_id": "p", "ok": True, "duration_s": 12})])
    return art


def test_watch_prints_the_story_and_stops_when_the_run_has_ended(art):
    m = json.loads((art / "manifest.json").read_text())
    m["end"] = {"state": "COMPLETED", "end_epoch": START + 700, "end_reason": "task_done"}
    (art / "manifest.json").write_text(json.dumps(m))
    write(art, "orchestrator", [(700, "state", {"from": "FINALIZING", "to": "COMPLETED"})])
    out = io.StringIO()
    assert watch.watch(art, out=out, poll_s=0.01) == 0  # returns on its own: no time limit, no hang
    text = out.getvalue()
    for expected in ("stage 0 given", 'turn 1 finished: "Stage 0 is done."', "stage 1 given to the agent (change request)",
                     "checkpoint 1: snapshot taken, est. cost so far $1.50", "HAZARD (context)",
                     "hidden tests 5/10 passing", "RUN ENDED: COMPLETED"):
        assert expected in text, (expected, text)


def test_status_and_latest_run(art, tmp_path):
    assert watch.find_run(tmp_path / "runs", None) == art
    assert watch.find_run(tmp_path / "runs", "latest") == art
    s = watch.status(art)
    assert "state     RUNNING" in s and "stage     1 given to the agent; 1 turns finished" in s
    assert "hidden tests 5/10 passing" in s
    with pytest.raises(FileNotFoundError):
        watch.find_run(tmp_path / "runs", "nope")
