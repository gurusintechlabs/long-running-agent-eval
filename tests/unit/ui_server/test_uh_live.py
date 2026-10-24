"""UH: weird payload types in the logs must not break /live."""
from __future__ import annotations

import pytest

from tests.unit.ui_server.conftest import AUTH, BASE, PORT, TOKEN
from tests.unit.ui_server.live_helpers import FakeRun
from ui_server import live_state, store

ODD = [5, "x", [1, 2], None, True, 1.5, {"m": 5}, {"m": [1]}, {"m": {"contextWindow": "big"}}, {"m": None}]


@pytest.fixture
def fake(runs_dir):
    r = FakeRun(runs_dir, budget_usd=1.0, duration_min=10, interval_min=2)
    yield r
    r.close()


@pytest.mark.parametrize("odd", ODD, ids=lambda o: repr(o)[:20])
def test_model_usage_of_any_shape(fake, odd):
    fake.append("agent_stream", "stream.result", {"modelUsage": odd})
    fake.append("agent_stream", "session.result", {"modelUsage": odd})
    s = live_state.RunLive(fake.dir).snapshot(store.read_json(fake.dir / "manifest.json"))
    assert "cost" in s


@pytest.mark.parametrize("odd", ODD, ids=lambda o: repr(o)[:20])
def test_payload_fields_of_any_shape(fake, odd):
    for src, typ in [("agent_stream", "tool.call"), ("agent_stream", "tool.result"),
                     ("agent_stream", "agent.test_run"), ("otel", "claude_code.api_request"),
                     ("orchestrator", "stage.delivered"), ("orchestrator", "run.clock"),
                     ("orchestrator", "platform.interruption"), ("guardrail", "guardrail.budget"),
                     ("guardrail", "guardrail.kill"), ("scorer", "scorer.hazard")]:
        fake.append(src, typ, {"tool": odd, "model": odd, "cost_usd": odd, "input_tokens": odd, "start_epoch": odd,
                               "offset_s": odd, "stage": odd, "kind": odd, "detail": odd, "reason": odd, "k": odd,
                               "is_error": odd, "severity": odd, "freeze_latency_ms": odd})
    s = live_state.RunLive(fake.dir).snapshot(store.read_json(fake.dir / "manifest.json"))
    assert "cost" in s


def test_non_object_json_lines_and_payloads(fake):
    p = fake.dir / "events" / "agent_stream.jsonl"
    with open(p, "ab") as fh:
        fh.write(b'[1,2]\n"str"\n5\nnull\n{"payload": 5, "type": "tool.call"}\n'
                 b'{"ts":"2026-01-01T00:00:00Z","mono_ns":1,"run_id":"r","source":"agent_stream",'
                 b'"type":"stream.result","seq":1,"payload":{"modelUsage":["a"]}}\n')
    s = live_state.RunLive(fake.dir).snapshot(store.read_json(fake.dir / "manifest.json"))
    assert "cost" in s


def test_endpoint_survives(client, runs_dir, fake):
    fake.append("agent_stream", "stream.result", {"modelUsage": [1, 2]})
    r = client.get(f"/api/runs/{fake.dir.name}/live")
    assert r.status_code == 200, r.text
