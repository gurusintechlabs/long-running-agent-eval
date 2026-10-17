"""Follow a run as a person would want to see it (``lrae status`` and ``lrae watch``).

Reads only the run's artifact folder (``runs/<run_id>/``): the event logs, snapshots and manifest.
``watch`` prints one line per meaningful event (stage delivered, turn finished, checkpoint scored,
hazard, guardrail action, run end) and keeps going until the run has ended and its last checkpoint
is scored. It has no time limit, so a multi-hour run needs it started only once.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from runner import manifest as mf

SOURCES = ("orchestrator", "guardrail", "scorer", "agent_stream")
TERMINAL = {"COMPLETED", "KILLED", "BUDGET_EXHAUSTED", "INTERRUPTED", "FAILED"}


def find_run(runs_dir: Path, run_id: str | None) -> Path:
    """``runs/<run_id>``, or the most recently started run when ``run_id`` is None or ``latest``."""
    runs_dir = Path(runs_dir)
    if run_id and run_id != "latest":
        path = runs_dir / run_id
        if not (path / "manifest.json").exists():
            raise FileNotFoundError(f"no run {run_id} in {runs_dir}")
        return path
    best, best_t = None, -1.0
    for m in runs_dir.glob("*/manifest.json"):
        try:
            t = float(mf.load(m).get("start_epoch") or 0)
        except (OSError, ValueError):
            continue
        if t > best_t:
            best, best_t = m.parent, t
    if best is None:
        raise FileNotFoundError(f"no runs in {runs_dir}")
    return best


class _Tail:
    def __init__(self, path: Path):
        self.path, self.offset, self.buf = path, 0, b""

    def read(self) -> list[dict]:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except OSError:
            return []
        self.offset += len(data)
        self.buf += data
        *lines, self.buf = self.buf.split(b"\n")
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


def _mins(t_s) -> str:
    return f"{float(t_s) / 60:6.1f}m" if isinstance(t_s, (int, float)) else "      "


def _clip(text: str, n: int = 110) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


class Watcher:
    """Turns raw events into human lines. ``feed`` returns the lines for one batch of events."""

    def __init__(self, art: Path):
        self.art = Path(art)
        self.start_epoch: float | None = None
        self.metrics: dict[tuple[str, int], dict[str, float | None]] = {}
        self.last_agent_text = ""
        self.cost = 0.0

    def _t(self, ev: dict) -> float | None:
        if self.start_epoch is None:
            return None
        try:
            return datetime.fromisoformat(ev["ts"].replace("Z", "+00:00")).timestamp() - self.start_epoch
        except (KeyError, ValueError):
            return None

    def feed(self, ev: dict) -> list[str]:
        typ, p = ev.get("type", ""), ev.get("payload") or {}
        t = _mins(p["t_s"]) if isinstance(p.get("t_s"), (int, float)) else _mins(self._t(ev))
        if typ == "run.clock":
            self.start_epoch = float(p.get("start_epoch") or 0)
            return [f"{_mins(0)}  run started"]
        if typ == "state" and p.get("to") in TERMINAL:
            return [f"{t}  RUN ENDED: {p['to']}"]
        if typ == "preflight.probe":
            bad = [c["name"] for c in p.get("checks", []) if not c.get("ok")]
            return [f"        pre-flight probe: {'all checks passed' if not bad else 'FAILED ' + ', '.join(bad)}"]
        if typ == "stage.delivered":
            kind = " (change request)" if p.get("kind") == "change_request" else ""
            return [f"{t}  stage {p.get('stage')} given to the agent{kind}"]
        if typ == "assistant.text":
            self.last_agent_text = p.get("text") or self.last_agent_text
            return []
        if typ == "claude_code.api_request":
            return []
        if typ == "turn.end":
            ok = "finished" if p.get("returncode") == 0 else f"FAILED (exit {p.get('returncode')})"
            said = f': "{_clip(self.last_agent_text)}"' if self.last_agent_text else ""
            self.last_agent_text = ""
            return [f"{t}  turn {p.get('turn')} {ok}{said}"]
        if typ == "run.done":
            return [f"{t}  agent finished all its work ({p.get('turns')} turns)"]
        if typ == "checkpoint":
            tag = f" ({p['final']})" if p.get("final") else ""
            return [f"{t}  checkpoint {p.get('k')}{tag}: snapshot taken, est. cost so far "
                    f"${float(p.get('cumulative_cost_usd') or 0):.2f}"]
        if typ == "scorer.metric":
            self.metrics.setdefault((p.get("pass_id"), p.get("k")), {})[p.get("name")] = p.get("value")
            if p.get("name") == "P":
                d = p.get("detail") or {}
                self.metrics[(p.get("pass_id"), p.get("k"))]["_P"] = f"{d.get('passed')}/{d.get('active', d.get('total'))}"
            return []
        if typ == "scorer.hazard":
            return [f"{_mins(p.get('t_detected_s'))}  HAZARD ({p.get('dimension')}): {_clip(p.get('evidence', ''))}"]
        if typ == "scorer.done":
            m = self.metrics.get((p.get("pass_id"), p.get("k")), {})
            if not p.get("ok"):
                return [f"        checkpoint {p.get('k')} scoring FAILED: {_clip(p.get('error', ''))}"]

            def f(n):
                v = m.get(n)
                return "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
            return [f"        checkpoint {p.get('k')} scored in {p.get('duration_s', 0):.0f}s: hidden tests "
                    f"{m.get('_P', '?')} passing, regressions {f('R')}, constraint breaks {f('C')}, "
                    f"rework {f('W')}, $/accepted commit {f('S')}"]
        if typ == "guardrail.violation" and p.get("severity") == "violation":
            return [f"{t}  GUARDRAIL {p.get('rule_id')}: {_clip(p.get('evidence', ''))}"]
        if typ == "guardrail.kill":
            return [f"{t}  KILL SWITCH ({p.get('reason')}): agent frozen in {p.get('freeze_latency_ms', 0):.0f} ms"]
        if typ == "platform.interruption":
            return [f"{t}  INTERRUPTION ({p.get('kind')}): {_clip(p.get('detail', ''))}"]
        if typ == "run.error":
            return [f"{t}  HARNESS ERROR: {_clip(p.get('error', ''))}"]
        return []


def _finished(art: Path) -> bool:
    """Run ended and its scorer queue drained (the manifest gets ``end`` after draining)."""
    try:
        return "end" in mf.load(art / "manifest.json")
    except (OSError, ValueError):
        return False


def watch(art: Path, *, out=sys.stdout, poll_s: float = 2.0, follow: bool = True) -> int:
    art = Path(art)
    w = Watcher(art)
    tails = [_Tail(art / "events" / f"{s}.jsonl") for s in SOURCES]
    print(f"watching {art.name}  (Ctrl-C stops watching; the run itself keeps going)", file=out, flush=True)
    while True:
        batch = [ev for tl in tails for ev in tl.read()]
        batch.sort(key=lambda e: e.get("ts", ""))
        for ev in batch:
            for line in w.feed(ev):
                print(line, file=out, flush=True)
        if not follow or _finished(art):
            # one last read: the final events may land just before the manifest is closed
            for ev in sorted((ev for tl in tails for ev in tl.read()), key=lambda e: e.get("ts", "")):
                for line in w.feed(ev):
                    print(line, file=out, flush=True)
            return 0
        time.sleep(poll_s)


def status(art: Path) -> str:
    """A short summary of where a run stands right now."""
    art = Path(art)
    m = mf.load(art / "manifest.json")
    end = m.get("end") or {}
    lines = [f"run       {m.get('run_id')}", f"task      {m.get('spec', {}).get('task', {}).get('id')}  "
             f"model {m.get('model') or m.get('runtime')}  config {m.get('config')}"]
    w = Watcher(art)
    last = {"stage": None, "checkpoint": None, "scored": None, "turns": 0, "t": None}
    for s in SOURCES:
        for ev in _Tail(art / "events" / f"{s}.jsonl").read():
            typ, p = ev.get("type"), ev.get("payload") or {}
            if typ == "run.clock":
                w.start_epoch = float(p.get("start_epoch") or 0)
            elif typ == "stage.delivered":
                last["stage"] = p.get("stage")
            elif typ == "turn.end":
                last["turns"] += 1
            elif typ == "checkpoint":
                last["checkpoint"] = p
            elif typ in ("scorer.metric", "scorer.done"):
                lines_ = w.feed(ev)
                if typ == "scorer.done" and lines_:
                    last["scored"] = lines_[0].strip()
    state = end.get("state") or "RUNNING"
    if w.start_epoch:
        elapsed = ((end.get("end_epoch") or time.time()) - w.start_epoch) / 60
        why = end.get("end_reason") or end.get("censored_reason")
        lines.append(f"state     {state}  after {elapsed:.1f} min" + (f"  ({why})" if why else ""))
    else:
        lines.append(f"state     {state}")
    if last["stage"] is not None:
        lines.append(f"stage     {last['stage']} given to the agent; {last['turns']} turns finished")
    cp = last["checkpoint"]
    if cp:
        lines.append(f"latest    checkpoint {cp.get('k')}, est. cost ${float(cp.get('cumulative_cost_usd') or 0):.2f}")
    if last["scored"]:
        lines.append(f"scores    {last['scored']}")
    return "\n".join(lines)
