import json

from scorer.determinism import compare_last_two


def _write(art, passes):
    ev = []
    for i, (k, metrics) in enumerate(passes):
        pid = f"p{i}"
        ev.append({"type": "scorer.start", "payload": {"k": k, "pass_id": pid}})
        ev += [{"type": "scorer.metric", "payload": {"k": k, "pass_id": pid, "name": n, "value": v}}
               for n, v in metrics.items()]
        ev.append({"type": "scorer.done", "payload": {"k": k, "pass_id": pid, "ok": True}})
    (art / "events").mkdir(parents=True)
    (art / "events" / "scorer.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ev))


def test_identical_passes_have_no_diff(tmp_path):
    _write(tmp_path, [(1, {"P": 0.5, "S": None}), (1, {"P": 0.5, "S": None})])
    assert compare_last_two(tmp_path) == {}


def test_changed_metric_and_missing_pass_are_reported(tmp_path):
    _write(tmp_path, [(1, {"P": 0.5, "X": 1.0}), (2, {"P": 1.0}), (1, {"P": 0.5, "X": 2.0})])
    diffs = compare_last_two(tmp_path)
    assert diffs[1] == {"X": (1.0, 2.0)}
    assert diffs[2] == {"_passes": (1, 2)}
