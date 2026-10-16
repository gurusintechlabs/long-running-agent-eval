import json

import pytest

from telemetry.counters import cumulative_cost


def write(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def api(cost):
    return {"type": "claude_code.api_request", "payload": {"cost_usd": cost}}


def test_sums_string_and_numeric_costs(tmp_path):
    # the live CLI exports cost_usd as a *string* attribute
    p = tmp_path / "otel.jsonl"
    write(p, [api("0.0063735"), api(0.01), api("0.02")])
    assert cumulative_cost(p) == pytest.approx(0.0363735)


def test_ignores_other_events_and_bad_values(tmp_path):
    p = tmp_path / "otel.jsonl"
    write(p, [{"type": "claude_code.user_prompt", "payload": {"cost_usd": "9"}}, api("n/a"), api(None), api("0.5")])
    p.write_text(p.read_text() + "not json\n")
    assert cumulative_cost(p) == pytest.approx(0.5)


def test_missing_file_is_zero(tmp_path):
    assert cumulative_cost(tmp_path / "nope.jsonl") == 0.0
