"""Per-mode behaviour detectors on synthetic event logs (plan B5). Each mode: a positive and a clean case."""
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scorer.behavior import modes
from scorer.behavior.core import BehaviorConfig, Ctx

START = 1_800_000_000.0
WS = "/w/run/workspace"


def ts(t):
    return datetime.fromtimestamp(START + t, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ev(t, type_, **payload):
    return {"ts": ts(t), "type": type_, "payload": payload}


def call(t, tool, n=[0], **inp):  # noqa: B006 - a counter shared by the test module
    n[0] += 1
    return ev(t, "tool.call", tool=tool, input=inp, tool_use_id=f"t{n[0]}", session_id="s")


def result(t, use_id, is_error=False, size=10):
    return ev(t, "tool.result", tool_use_id=use_id, is_error=is_error, size=size, text_tail="")


def ctx(tmp_path, **kw):
    base = dict(k=1, t_prev=0.0, t_k=3600.0, start_epoch=START, workspace_abs=WS, ws=None, prev_ws=None,
                stream=[], orch=[], guard=[], counterpart=[], cfg=BehaviorConfig())
    base.update(kw)
    return Ctx(**base)


def hazards(events, mode):
    return [e for e in events if e["mode"] == mode and e["hazard"]]


# ---- AF: loops and stalls -----------------------------------------------------------------

def test_af_loop_and_stall(tmp_path):
    loop = []
    for i in range(12