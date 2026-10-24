"""Label review: items to decide on, and the append-only decision log (docs/ui-api-specs.md).

Items come from pluggable sources (``SOURCES``); the built-ins read what the scorer already wrote to the run
(``events/scorer.jsonl``: hazards and behaviour events, read-only) and an optional hand-made
``review-items.json``. Decisions are appended to ``runs/<run_id>/review.jsonl``: one JSON object per line,
never rewritten; the latest line per item wins when read, the whole history stays retrievable.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import math
import os
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from ui_server import safefs

DECISIONS = ("confirm", "reject", "unsure")
NOTE_MAX = 2000
LINE_MAX = 16 * 1024            # one decision line, bytes
FILE_MAX = 5 * 1024 * 1024      # review.jsonl size cap, bytes
BATCH_MAX = 500
REVIEW_FILE = "review.jsonl"

Source = Callable[[Path], Iterable[dict]]


class ReviewError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# --- sources --------------------------------------------------------------------------------------------

def _item_id(prefix: str, *parts: object) -> str:
    return prefix + "-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:14]


_cache: dict[Path, tuple[tuple[int, int], list[dict]]] = {}
TEXT_MAX = 300
EVIDENCE_MAX = 4000


def as_k(v) -> int | None:
    """A checkpoint number: an int >= 0, or a string of digits; anything else is not one."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if 0 <= v < 10**6 else None
    if isinstance(v, str) and v.isascii() and v.isdigit() and len(v) <= 6:
        return int(v)
    return None


def as_num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v if math.isfinite(v) else None


def as_text(v, limit: int = TEXT_MAX) -> str:
    if isinstance(v, str):
        return v[:limit]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)[:limit]
    return ""


def as_evidence(v):
    """Evidence is shown, so it must stay JSON, but bounded; non-conforming shapes become text."""
    if v is None or isinstance(v, str):
        return v[:EVIDENCE_MAX] if isinstance(v, str) else None
    try:
        text = json.dumps(v, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError, RecursionError):
        return None
    return v if len(text) <= EVIDENCE_MAX else text[:EVIDENCE_MAX]


def scorer_events(run_dir: Path) -> list[dict]:
    """Hazards and behaviour events of the last successful scoring pass of each checkpoint. Events that do
    not conform (no integer ``k``, payload not an object) are dropped; scalar fields are coerced."""
    f = run_dir / "events" / "scorer.jsonl"
    st = safefs.stat_file(f)
    if st is None:
        return []
    sig = (st.st_mtime_ns, st.st_size)
    hit = _cache.get(f)
    if hit and hit[0] == sig:
        return hit[1]
    last_ok: dict[int, str] = {}
    last_start: dict[int, str] = {}
    events: list[dict] = []
    with safefs.open_file(f, "r") as fh:
        for line in fh or ():
            if '"scorer.behavior"' in line or '"scorer.hazard"' in line:
                kind = "behavior" if '"scorer.behavior"' in line else "hazard"
            elif '"scorer.done"' in line or '"scorer.start"' in line:
                kind = "done" if '"scorer.done"' in line else "start"
            else:
                continue
            try:
                rec = json.loads(line)
                p = rec["payload"]
                k = as_k(p["k"])
                pid = as_text(p.get("pass_id"), 100) or None
            except (ValueError, KeyError, TypeError, RecursionError, AttributeError):
                continue
            if k is None:
                continue
            if kind == "start":
                last_start[k] = pid
            elif kind == "done":
                if p.get("ok") is True:
                    last_ok[k] = pid
            else:
                events.append({"kind": kind, "ts": as_text(rec.get("ts"), 40) or None, "p": p, "k": k, "pid": pid})
    chosen = {**last_start, **last_ok}
    seen: Counter = Counter()
    items: list[dict] = []
    for e in events:
        p, kind, k = e["p"], e["kind"], e["k"]
        if chosen.get(k) not in (None, e["pid"]):
            continue
        name = as_text(p.get("detector") or p.get("rule"))
        group = as_text(p.get("mode") or p.get("dimension"))
        t_s = as_num(p.get("t_s") if kind == "behavior" else p.get("t_attributed_s"))
        ev = as_evidence(p.get("evidence"))
        base = (kind, k, group, name, t_s, json.dumps(ev, sort_keys=True, default=str))
        seen[base] += 1
        items.append({
            "item_id": _item_id("h" if kind == "hazard" else "b", *base, seen[base]),
            "source": "scorer_events", "kind": kind, "k": k, "t_s": t_s,
            "group": group, "name": name, "dimension": as_text(p.get("dimension")) or None,
            "hazard": kind == "hazard" or p.get("hazard") is True,
            "deterministic": p.get("deterministic") if isinstance(p.get("deterministic"), bool) else None,
            "evidence": ev, "title": f"{group} {name}".strip(),
            "context": {"pass_id": e["pid"], "ts": e["ts"],
                        "cursor": {"k": k, "t_s": t_s, "t_detected_s": as_num(p.get("t_detected_s"))}},
        })
    items.sort(key=lambda i: (i["k"], i["t_s"] if i["t_s"] is not None else 0, i["item_id"]))
    _cache[f] = (sig, items)
    return items


def _json_doc(path: Path):
    raw = safefs.read_bytes(path, 8 * 1024 * 1024)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, RecursionError):
        return None


def file_items(run_dir: Path) -> list[dict]:
    """Optional ``review-items.json``: ``{"items": [{"id", "title", "evidence", "group", "name", ...}]}``.
    Items that do not conform are dropped; fields are coerced to the types the API promises."""
    doc = _json_doc(run_dir / "review-items.json")
    raw_items = doc.get("items") if isinstance(doc, dict) else None
    out = []
    for it in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(it, dict) or not isinstance(it.get("id"), str) or not it["id"]:
            continue
        prop = it.get("proposed_label")
        out.append({"item_id": "f-" + it["id"][:80], "source": "file",
                    "kind": as_text(it.get("kind"), 40) or "label",
                    "k": as_k(it.get("k")), "t_s": as_num(it.get("t_s")),
                    "group": as_text(it.get("group")), "name": as_text(it.get("name")),
                    "dimension": as_text(it.get("dimension")) or None, "hazard": it.get("hazard") is True,
                    "deterministic": it.get("deterministic") if isinstance(it.get("deterministic"), bool) else None,
                    "evidence": as_evidence(it.get("evidence")),
                    "title": as_text(it.get("title")) or it["id"][:TEXT_MAX],
                    "context": it.get("context") if isinstance(it.get("context"), dict) else {},
                    "proposed_label": prop if prop in DECISIONS else None,
                    "draft_note": as_text(it.get("draft_note"), NOTE_MAX) or None})
    return out


SOURCES: dict[str, Source] = {"scorer_events": scorer_events, "file": file_items}


def _draft_labels(run_dir: Path) -> list[dict]:
    """Optional ``review-draft.json``: ``{"labels": [{"match": {"kind", "group", "name", "k"}, "proposed": "confirm",
    "note": "..."}]}``, proposed (draft) labels that are attached to matching items. They are suggestions only."""
    doc = _json_doc(run_dir / "review-draft.json")
    labels = doc.get("labels") if isinstance(doc, dict) else None
    return [x for x in labels if isinstance(x, dict) and isinstance(x.get("match"), dict)] \
        if isinstance(labels, list) else []


def run_items(run_dir: Path) -> list[dict]:
    drafts = _draft_labels(run_dir)
    out: list[dict] = []
    for name in sorted(SOURCES):
        for it in SOURCES[name](run_dir):
            it = {**it, "run_id": run_dir.name}
            if it.get("proposed_label") is None:
                for d in drafts:
                    if all(it.get(k) == v for k, v in d["match"].items()):
                        it["proposed_label"] = d.get("proposed")
                        it["draft_note"] = d.get("note")
                        break
            out.append(it)
    return out


# --- decisions ------------------------------------------------------------------------------------------

def review_path(run_dir: Path) -> Path:
    return run_dir / REVIEW_FILE


def read_history(run_dir: Path) -> list[dict]:
    """All decision records in file order. Unreadable lines are skipped (they are never rewritten)."""
    out: list[dict] = []
    with safefs.open_file(review_path(run_dir), "r") as fh:
        for line in fh or ():
            try:
                rec = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if isinstance(rec, dict) and isinstance(rec.get("item_id"), str) and rec.get("decision") in DECISIONS:
                out.append(rec)
    return out


def latest(history: list[dict]) -> dict[str, dict]:
    cur: dict[str, dict] = {}
    for rec in history:
        cur[rec["item_id"]] = rec
    return cur


def _reviewer() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "local"


def append_decisions(run_dir: Path, decisions: list[dict]) -> list[dict]:
    """Validate every decision against the run's items, then append one line each (single ``write`` with
    ``O_APPEND``). All-or-nothing on validation."""
    if not decisions:
        raise ReviewError(400, "no decisions")
    if len(decisions) > BATCH_MAX:
        raise ReviewError(413, f"at most {BATCH_MAX} decisions per request")
    known = {i["item_id"] for i in run_items(run_dir)}
    lines: list[tuple[bytes, dict]] = []
    ts = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    for d in decisions:
        if d.get("item_id") not in known:
            raise ReviewError(404, f"unknown item: {str(d.get('item_id'))[:100]}")
        if d.get("decision") not in DECISIONS:
            raise ReviewError(422, f"decision must be one of {DECISIONS}")
        note = d.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > NOTE_MAX):
            raise ReviewError(422, f"note must be a string of at most {NOTE_MAX} characters")
        rec = {"ts": ts, "run_id": run_dir.name, "item_id": d["item_id"], "decision": d["decision"],
               "note": note or None, "reviewer": _reviewer()}
        raw = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(raw) > LINE_MAX:
            raise ReviewError(413, "decision line too large")
        lines.append((raw, rec))
    path = review_path(run_dir)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    except OSError as exc:
        raise ReviewError(500, f"cannot open review log: {exc.strerror}") from exc
    try:
        if os.fstat(fd).st_size + sum(len(b) for b, _ in lines) > FILE_MAX:
            raise ReviewError(413, "review log size cap reached")
        for raw, _ in lines:
            if os.write(fd, raw) != len(raw):
                raise ReviewError(500, "short write to review log")
    finally:
        os.close(fd)
    return [r for _, r in lines]


def counts(items: list[dict], cur: dict[str, dict]) -> dict[str, int]:
    c = Counter(cur[i["item_id"]]["decision"] if i["item_id"] in cur else "pending" for i in items)
    return {k: c.get(k, 0) for k in ("pending", *DECISIONS)}
