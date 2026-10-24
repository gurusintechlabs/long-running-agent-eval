"""Safety panel data from ``events/guardrail.jsonl`` (+ scorer behaviour signals), read-only and incremental
(docs/ui-api-live.md §5).

Incidents are the ``guardrail.violation`` events. A ``guardrail.kill`` is attached to the incident of the
same rule that asked for it (for a budget kill: the ``budget`` violation, which also carries the
preceding ``guardrail.budget`` figures). Telemetry stall/resume pairs are folded into one noise summary
and never count towards the status. Every incident gets a *context window*: the refs of the agent-stream
events around the triggering tool call, so the UI can link to the transcript.
"""
from __future__ import annotations

import bisect
import json
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from ui_server import rule_docs
from ui_server.feed import RunClock, level_of, sanitize, ts_epoch
from ui_server.live_state import num
from ui_server.tailer import MAX_LINE, FileTail, make_ref, peek

EVIDENCE_CAP = 2000
FREEZE_TARGET_MS = 2000.0          # spec §7.3: detection to frozen process group
CONTEXT_BEFORE, CONTEXT_AFTER = 20, 5
INDEX_MAX = 500_000
LIST_CAP = 200
_SEQ = re.compile(rb'"seq"\s*:\s*(\d+)')
_SEV_RANK = {"warning": 1, "violation": 2}
_STATUS_ORDER = ("clear", "warnings", "violations", "killed")

_QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'")
_CMD_FORM = re.compile(r"^(?P<tool>[A-Za-z_.]+): (?P<cmd>.*?) -> '(?P<path>.*?)' resolves to ")
_MATCH_FORM = re.compile(r"^'(?P<hit>.*?)' in ")


def clean_text(text, cap: int = EVIDENCE_CAP) -> tuple[str, bool]:
    """Plain text safe to show: control characters (except newline and tab) and bidi overrides removed."""
    s = text if isinstance(text, str) else "" if text is None else str(text)
    out = []
    for c in s:
        o = ord(c)
        if c in "\n\t" or (o >= 0x20 and o != 0x7F and not (0x80 <= o <= 0x9F)
                           and c not in "​‌‍‎‏‪‫‬‭‮"
                                        "⁦⁧⁨⁩﻿  "):
            out.append(c)
        else:
            out.append(" ")
    s = "".join(out)
    return (s[:cap], True) if len(s) > cap else (s, False)


def highlight_spans(evidence: str) -> list[list[int]]:
    """Character ranges ``[start, end]`` in ``evidence`` worth highlighting: the matched command text
    or the offending path. A hint for the UI; empty when the evidence has no recognisable form."""
    m = _MATCH_FORM.match(evidence)
    if m and m.group("hit"):
        return [[m.start("hit"), m.end("hit")]]
    spans: list[list[int]] = []
    m = _CMD_FORM.match(evidence)
    if m:
        if m.group("tool") == "Bash" and m.group("cmd"):
            spans.append([m.start("cmd"), m.end("cmd")])
        if m.group("path"):
            spans.append([m.start("path"), m.end("path")])
        return spans
    q = _QUOTED.search(evidence)
    if q and q.group(1):
        return [[q.start(1), q.end(1)]]
    return []


class StreamIndex:
    """Sparse index of the visible (info-level) agent-stream events: ``(seq, line offset, ts)``.
    Built from the envelope prefixes only, incrementally; raw ``stream.*`` echoes are left out."""

    def __init__(self, path: Path):
        self.tail = FileTail(path)
        self.seqs: list[int] = []
        self.offs: list[int] = []
        self.tss: list[str] = []
        self.types: list[str] = []

    def update(self) -> None:
        while True:
            lines, at_eof = self.tail.read(8 << 20)
            if self.tail.restarted:
                self.tail.restarted = False
                self.seqs, self.offs, self.tss, self.types = [], [], [], []
            for ln in lines:
                if ln.data is None or len(self.seqs) >= INDEX_MAX:
                    continue
                pk = peek(ln.data)
                if pk is None or level_of("agent_stream", pk[1]) != "info":
                    continue
                m = _SEQ.search(ln.data[:700])
                if m is None:
                    continue
                self.seqs.append(int(m.group(1)))
                self.offs.append(ln.start)
                self.tss.append(pk[0])
                self.types.append(pk[1])
            if at_eof:
                return

    def window(self, seq: int | None, ts: str | None, before: int, after: int) -> dict | None:
        """Refs around ``seq`` (or, without a seq, the first event at or after ``ts``)."""
        if not self.seqs:
            return None
        i = None
        if isinstance(seq, int):
            j = bisect.bisect_left(self.seqs, seq)
            if j >= len(self.seqs):
                return None            # the stream file does not reach that seq (excerpt or lagging copy)
            i = j
        elif ts:
            j = bisect.bisect_left(self.tss, ts)
            i = min(j, len(self.seqs) - 1)
        if i is None:
            return None
        lo, hi = max(0, i - before), min(len(self.seqs) - 1, i + after)
        return {"source": "agent_stream",
                "center_ref": make_ref("agent_stream", self.offs[i]), "center_seq": self.seqs[i],
                "from_ref": make_ref("agent_stream", self.offs[lo]), "from_seq": self.seqs[lo],
                "to_ref": make_ref("agent_stream", self.offs[hi]), "to_seq": self.seqs[hi],
                "before": i - lo, "after": hi - i, "count": hi - lo + 1,
                "exact": isinstance(seq, int) and self.seqs[i] == seq}


class RunSafety:
    """Incident list for one run, folded incrementally from guardrail.jsonl (and scorer.jsonl)."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.lock = threading.RLock()
        self.reset()
        self.index = StreamIndex(self.run_dir / "events" / "agent_stream.jsonl")

    def reset(self) -> None:
        self.gtail = FileTail(self.run_dir / "events" / "guardrail.jsonl")
        self.stail = FileTail(self.run_dir / "events" / "scorer.jsonl")
        self.incidents: list[dict] = []
        self.pending_budget: dict | None = None
        self.kills: list[dict] = []
        self.budget_events: list[dict] = []
        self.interruptions: list[dict] = []
        self.noise = {"pairs": 0, "open": False, "total_paused_s": 0.0, "max_paused_s": 0.0, "reasons": {},
                      "silence_sum": 0.0, "silence_n": 0, "first_ref": None, "last_ref": None,
                      "first_ts": None, "last_ts": None}
        self.monitor = {"status": None, "errors": []}
        self.other = {"procmon_events": 0, "kill_errors": []}
        self.passes: OrderedDict[str, dict] = OrderedDict()
        self.invalid = 0

    # -- reading -----------------------------------------------------------------------------
    def update(self) -> None:
        with self.lock:
            for tail, fn in ((self.gtail, self._guard), (self.stail, self._scorer)):
                while True:
                    lines, at_eof = tail.read(8 << 20)
                    if tail.restarted:
                        tail.restarted = False
                        self.reset()
                        return self.update()
                    for ln in lines:
                        if ln.data is None or len(ln.data) > MAX_LINE:
                            continue
                        pk = peek(ln.data)
                        if pk is None:
                            self.invalid += 1
                            continue
                        if fn is self._scorer and pk[1] not in ("scorer.behavior", "scorer.hazard", "scorer.done"):
                            continue
                        try:
                            ev = json.loads(ln.data)
                        except ValueError:
                            self.invalid += 1
                            continue
                        p = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
                        fn(pk[1], p, ev, ln.start)
                    if at_eof:
                        break
            self.index.update()

    def _guard(self, typ, p, ev, off):
        ts = ev.get("ts") if isinstance(ev.get("ts"), str) else None
        ref = make_ref("guardrail", off)
        if typ == "guardrail.violation":
            inc = {"id": ref, "cursor": ref, "seq": ev.get("seq"), "ts": ts,
                   "rule_id": str(p.get("rule_id"))[:120], "severity": p.get("severity"),
                   "action": p.get("action"), "channel": p.get("channel"),
                   "evidence_raw": p.get("evidence"), "stream_seq": p.get("stream_seq")
                   if isinstance(p.get("stream_seq"), int) else None, "kill": None, "budget": None}
            if inc["rule_id"] == "budget" and self.pending_budget is not None:
                inc["budget"], self.pending_budget = self.pending_budget, None
            self.incidents.append(inc)
        elif typ == "guardrail.kill":
            k = {"rule_id": str(p.get("rule_id"))[:120], "reason": p.get("reason"),
                 "detect_mono_ns": p.get("detect_mono_ns") if isinstance(p.get("detect_mono_ns"), int) else None,
                 "frozen_mono_ns": p.get("frozen_mono_ns") if isinstance(p.get("frozen_mono_ns"), int) else None,
                 "freeze_latency_ms": num(p.get("freeze_latency_ms")), "ts": ts, "cursor": ref}
            self.kills.append(k)
            target = next((i for i in reversed(self.incidents)
                           if i["rule_id"] == k["rule_id"] and i["kill"] is None
                           and (i["action"] == "kill" or k["rule_id"] == "budget")), None)
            if target is None:
                target = {"id": ref, "cursor": ref, "seq": ev.get("seq"), "ts": ts, "rule_id": k["rule_id"],
                          "severity": "violation", "action": "kill", "channel": None,
                          "evidence_raw": "(a kill was recorded without a matching violation event)",
                          "stream_seq": None, "kill": None, "budget": None, "synthetic": True}
                self.incidents.append(target)
            target["kill"] = k
        elif typ == "guardrail.budget":
            b = {k: p.get(k) for k in ("cost_usd", "tokens", "per_run_usd", "per_run_tokens")}
            b["ts"], b["cursor"] = ts, ref
            self.budget_events.append(b)
            self.pending_budget = b
        elif typ == "guardrail.budget_extended":
            self.budget_events.append({"extended": True, "ts": ts, "cursor": ref,
                                       **{k: p.get(k) for k in ("from_usd", "to_usd", "from_tokens", "to_tokens")},
                                       "reason": str(p.get("reason"))[:300]})
        elif typ == "guardrail.telemetry_stalled":
            n = self.noise
            n["open"] = True
            r = str(p.get("reason") or "?")[:40]
            n["reasons"][r] = n["reasons"].get(r, 0) + 1
            s = num(p.get("silence_s"))
            if s is not None:
                n["silence_sum"] += s
                n["silence_n"] += 1
            n["first_ref"] = n["first_ref"] or ref
            n["first_ts"] = n["first_ts"] or ts
            n["last_ref"], n["last_ts"] = ref, ts
        elif typ == "guardrail.telemetry_resumed":
            n = self.noise
            n["open"] = False
            n["pairs"] += 1
            d = num(p.get("paused_s")) or 0.0
            n["total_paused_s"] += d
            n["max_paused_s"] = max(n["max_paused_s"], d)
            n["first_ref"] = n["first_ref"] or ref
            n["first_ts"] = n["first_ts"] or ts
            n["last_ref"], n["last_ts"] = ref, ts
        elif typ == "guardrail.monitor":
            self.monitor["status"] = p.get("status")
            if p.get("status") == "error":
                self.monitor["errors"].append({"error": str(p.get("error"))[:300], "ts": ts})
                del self.monitor["errors"][:-10]
        elif typ == "guardrail.kill_error":
            self.other["kill_errors"].append({"step": p.get("step"), "error": str(p.get("error"))[:300], "ts": ts})
        elif typ == "platform.interruption":
            self.interruptions.append({"kind": p.get("kind"), "detail": str(p.get("detail"))[:300], "ts": ts,
                                       "cursor": ref})
        elif typ.startswith("procmon."):
            self.other["procmon_events"] += 1

    def _scorer(self, typ, p, ev, off):
        pid = str(p.get("pass_id") or "")
        ps = self.passes.setdefault(pid, {"k": p.get("k"), "ok": None, "behavior": [], "hazards": []})
        ref = make_ref("scorer", off)
        if typ == "scorer.done":
            ps["ok"] = bool(p.get("ok"))
            ps["k"] = p.get("k", ps["k"])
        elif typ == "scorer.behavior" and len(ps["behavior"]) < 2000:
            ps["behavior"].append((ref, ev.get("ts"), p))
        elif typ == "scorer.hazard" and len(ps["hazards"]) < 200:
            ps["hazards"].append((ref, ev.get("ts"), p))
        while len(self.passes) > 400:
            self.passes.popitem(last=False)

    # -- output ------------------------------------------------------------------------------
    def build(self, *, manifest: dict, policy: rule_docs.PolicyInfo, clock: RunClock, budget: dict | None,
              scrub: Callable[[str], str], limit: int = LIST_CAP, group_ids: int = 50) -> dict:
        self.update()
        with self.lock:
            return self._build(manifest, policy, clock, budget, scrub, max(1, min(limit, 1000)), group_ids)

    def _t(self, clock: RunClock, ts):
        return clock.t_s(ts_epoch(ts))

    def _incident(self, i: dict, policy, clock, scrub) -> dict:
        ev_text, cut = clean_text(i["evidence_raw"])
        ev_text = scrub(ev_text)
        expl = rule_docs.explain(i["rule_id"], policy)
        sev = i["severity"] if i["severity"] in _SEV_RANK else "warning"
        act = i["action"] if i["action"] in ("log", "kill") else "log"
        k = i["kill"]
        out = {
            "id": i["id"], "cursor": i["cursor"], "seq": i["seq"], "ts": i["ts"], "t_s": self._t(clock, i["ts"]),
            "rule_id": sanitize(i["rule_id"], 120), "title": expl["title"], "category": expl["category"],
            "severity": sev, "action": act,
            "channel": sanitize(i["channel"], 40) if isinstance(i["channel"], str) else None,
            "evidence": ev_text, "evidence_truncated": cut, "evidence_highlight": highlight_spans(ev_text),
            "explanation": expl["protects"], "why_it_matters": expl["why"],
            "killed": k is not None, "stream_seq": i["stream_seq"],
            "context": self.index.window(i["stream_seq"], i["ts"], CONTEXT_BEFORE, CONTEXT_AFTER),
            "synthetic": bool(i.get("synthetic")),
        }
        if k is not None:
            out["kill"] = self._kill(k, clock)
        if i["budget"] is not None:
            out["budget"] = {kk: i["budget"].get(kk) for kk in ("cost_usd", "tokens", "per_run_usd", "per_run_tokens")}
        return out

    def _kill(self, k: dict, clock) -> dict:
        d, f = k["detect_mono_ns"], k["frozen_mono_ns"]
        delay = (f - d) / 1e6 if d is not None and f is not None and f >= d else None
        lat = k["freeze_latency_ms"]
        shown = delay if delay is not None else lat
        return {"rule_id": sanitize(k["rule_id"], 120), "reason": sanitize(k["reason"], 40) if k["reason"] else None,
                "detect_mono_ns": d, "frozen_mono_ns": f, "detect_to_freeze_ms": delay,
                "reported_freeze_latency_ms": lat, "target_ms": FREEZE_TARGET_MS,
                "within_target": (shown <= FREEZE_TARGET_MS) if shown is not None else None,
                "ts": k["ts"], "t_s": self._t(clock, k["ts"]), "cursor": k["cursor"]}

    def _build(self, manifest, policy, clock, budget, scrub, limit, group_ids):
        raw = self.incidents
        has_kill = bool(self.kills)
        worst = "violations" if any(i["severity"] == "violation" for i in raw) else "warnings" if raw else "clear"
        status = "killed" if has_kill else worst
        shown = [self._incident(i, policy, clock, scrub) for i in raw[-limit:]]
        # groups by rule, from the raw records (cheap even for thousands of incidents)
        groups: dict[str, dict] = {}
        expl_cache: dict[str, dict] = {}
        for i in raw:
            rid = sanitize(i["rule_id"], 120)
            ex = expl_cache.get(rid) or expl_cache.setdefault(rid, rule_docs.explain(i["rule_id"], policy))
            sev = i["severity"] if i["severity"] in _SEV_RANK else "warning"
            g = groups.setdefault(rid, {
                "rule_id": rid, "title": ex["title"], "category": ex["category"], "explanation": ex["protects"],
                "count": 0, "severity": "warning", "action": "log", "killed": False, "channels": [],
                "first_ts": i["ts"], "first_t_s": self._t(clock, i["ts"]), "last_ts": i["ts"], "last_t_s": None,
                "sample_evidence": scrub(clean_text(i["evidence_raw"], 300)[0]), "incident_ids": []})
            g["count"] += 1
            if _SEV_RANK[sev] > _SEV_RANK[g["severity"]]:
                g["severity"] = sev
            if i["action"] == "kill":
                g["action"] = "kill"
            g["killed"] = g["killed"] or i["kill"] is not None
            ch = sanitize(i["channel"], 40) if isinstance(i["channel"], str) else None
            if ch and ch not in g["channels"]:
                g["channels"].append(ch)
            g["last_ts"] = i["ts"]
            g["incident_ids"].append(i["id"])
        for g in groups.values():
            g["last_t_s"] = self._t(clock, g["last_ts"])
            g["incident_ids"] = g["incident_ids"][-group_ids:][::-1]
        glist = sorted(groups.values(), key=lambda g: (not g["killed"], -_SEV_RANK[g["severity"]], -g["count"],
                                                       g["rule_id"]))
        rules = {g["rule_id"]: expl_cache[g["rule_id"]] for g in glist}
        for r in rules.values():       # the policy text comes from a file: keep it plain and bounded
            if r["policy"] and isinstance(r["policy"].get("match"), str):
                r["policy"]["match"] = scrub(r["policy"]["match"])[:1000]
        n = self.noise
        noise = []
        if n["pairs"] or n["open"]:
            typical = round(n["silence_sum"] / n["silence_n"]) if n["silence_n"] else None
            noise.append({
                "kind": "telemetry_stall", "id": "fold:telemetry_stall",
                "title": "Telemetry silent" + (f" ~{typical} s" if typical else "") + f" x {n['pairs'] + int(n['open'])}",
                "pairs": n["pairs"], "open": n["open"], "typical_silence_s": typical,
                "total_paused_s": round(n["total_paused_s"], 3), "max_paused_s": round(n["max_paused_s"], 3),
                "reasons": dict(n["reasons"]), "first_cursor": n["first_ref"], "last_cursor": n["last_ref"],
                "first_ts": n["first_ts"], "last_ts": n["last_ts"],
                "explanation": "The OTel stream went quiet, so the guardrail could not see spend; it paused the agent "
                               "until records resumed. Not a rule violation and not counted in the status."})
        end = manifest.get("end") if isinstance(manifest.get("end"), dict) else None
        kill = None
        if self.kills:
            k0 = self.kills[0]
            kill = self._kill(k0, clock)
            host_raw = next((i for i in raw if i["kill"] is not None and i["kill"]["cursor"] == k0["cursor"]), None)
            host = self._incident(host_raw, policy, clock, scrub) if host_raw else None
            kill.update({"incident_id": host["id"] if host else None,
                         "evidence": host["evidence"] if host else None,
                         "evidence_highlight": host["evidence_highlight"] if host else [],
                         "explanation": host["explanation"] if host else rule_docs.explain(k0["rule_id"], policy)["protects"],
                         "context": host["context"] if host else None,
                         "budget": host.get("budget") if host else None,
                         "run_state": end.get("state") if end else None})
        return {
            "run_id": manifest.get("run_id") or self.run_dir.name,
            "status": status, "status_order": list(_STATUS_ORDER),
            "counts": {"incidents": len(raw), "violations": sum(i["severity"] == "violation" for i in raw),
                       "warnings": sum(i["severity"] != "violation" for i in raw), "kills": len(self.kills)},
            "kill": kill, "kills": [self._kill(k, clock) for k in self.kills[:5]],
            "incidents": shown[::-1], "incidents_total": len(raw), "incidents_truncated": len(raw) > limit,
            "groups": glist, "rules": rules, "noise": noise,
            "budget": {"meter": budget, "events": self.budget_events[-20:]},
            "monitor": {"status": self.monitor["status"], "errors": self.monitor["errors"],
                        "kill_errors": self.other["kill_errors"], "procmon_events": self.other["procmon_events"]},
            "interruptions": self.interruptions[-20:],
            "policy": {"source": policy.source, "file": policy.path, "verified": policy.verified,
                       "sha256": policy.sha256, "manifest_sha256": manifest.get("policy_sha256"), "note": policy.note},
            "scorer_signals": self._signals(scrub),
            "context_window": {"before": CONTEXT_BEFORE, "after": CONTEXT_AFTER, "source": "agent_stream",
                              "unit": "visible (info-level) events"},
            "problems": {"invalid_lines": self.invalid},
        }

    def _signals(self, scrub) -> dict:
        by_k: dict = {}
        for ps in self.passes.values():
            if ps["ok"]:
                by_k[ps["k"]] = ps          # the last successful pass of each checkpoint wins
        beh, haz = [], []
        for k, ps in sorted(by_k.items(), key=lambda kv: (kv[0] is None, kv[0] if isinstance(kv[0], int) else 0)):
            for ref, _ts, p in ps["behavior"]:
                ev, _ = clean_text(p.get("evidence"), 600)
                beh.append({"cursor": ref, "k": k, "mode": sanitize(p.get("mode"), 12) if p.get("mode") else None,
                            "detector": sanitize(p.get("detector"), 80) if p.get("detector") else None,
                            "t_s": num(p.get("t_s")), "hazard": bool(p.get("hazard")),
                            "dimension": sanitize(p.get("dimension"), 20) if p.get("dimension") else None,
                            "deterministic": p.get("deterministic"), "evidence": scrub(ev)})
            for ref, _ts, p in ps["hazards"]:
                ev, _ = clean_text(p.get("evidence"), 600)
                haz.append({"cursor": ref, "k": k, "dimension": sanitize(p.get("dimension"), 20),
                            "rule": sanitize(p.get("rule"), 60), "t_detected_s": num(p.get("t_detected_s")),
                            "t_attributed_s": num(p.get("t_attributed_s")), "evidence": scrub(ev)})
        beh.sort(key=lambda b: (b["t_s"] is None, b["t_s"] or 0))
        by_det: dict[str, int] = {}
        for b in beh:
            key = f"{b['mode']}/{b['detector']}"
            by_det[key] = by_det.get(key, 0) + 1
        return {"behavior": beh[-LIST_CAP:], "behavior_total": len(beh), "behavior_hazards": sum(b["hazard"] for b in beh),
                "behavior_by_detector": dict(sorted(by_det.items(), key=lambda kv: -kv[1])[:30]),
                "hazards": haz[-LIST_CAP:], "hazards_total": len(haz),
                "note": "From the scorer (after each checkpoint is scored), not the live guardrail."}


class SafetyRegistry:
    def __init__(self, size: int = 8):
        self.size = size
        self._d: OrderedDict[str, RunSafety] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, run_dir: Path) -> RunSafety:
        key = str(run_dir)
        with self._lock:
            rs = self._d.pop(key, None) or RunSafety(run_dir)
            self._d[key] = rs
            while len(self._d) > self.size:
                self._d.popitem(last=False)
            return rs


REGISTRY = SafetyRegistry()
