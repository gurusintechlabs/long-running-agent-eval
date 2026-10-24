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
import os
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

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


def scorer_events(run_dir: Path) -> list[dict]:
    """Hazards and behaviour events of the last successful scoring pass of each checkpoint."""
    f = run_dir / "events" / "scorer.jsonl"
    try:
        st = f.stat()
    except OSError:
        return []
    sig = (st.st_mtime_ns, st.st_size)
    hit = _cache.get(f)
    if hit and hit[0] == sig:
        return hit[1]
    last_ok: dict[int, str] = {}
    last_start: dict[int, str] = {}
    events: list[dict] = []
    with open(f, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"scorer.behavior"' in line or '"scorer.hazard"' in line:
                kind = "behavior" if '"scorer.behavior"' in line else "hazard"
            elif '"scorer.done"' in line or '"scorer.start"' in line:
                kind = "done" if '"scorer.done"' in line else "start"
            else:
                continue
            try:
                rec = json.loads(line)
                p = rec["payload"]
                k, pid = int(p["k"]), p.get("pass_id")
            except (ValueError, KeyError, TypeError):
                continue
            if kind == "start":
                last_start[k] = pid
            elif kind == "done":
                if p.get("ok"):
                    last_ok[k] = pid
            else:
                events.append({"kind": kind, "ts": rec.get("ts"), "p": p})
    chosen = {**last_start, **last_ok}
    seen: Counter = Counter()
    items: list[dict] = []
    for e in events:
        p, kind = e["p"], e["kind"]
        if chosen.get(p["k"]) not in (None, p.get("pass_id")):
            continue
        name = p.get("detector") or p.get("rule") or ""
        group = p.get("mode") or p.get("dimension") or ""
        t_s = p.get("t_s") if kind == "behavior" else p.get("t_attributed_s")
        base = (kind, p["k"], group, name, t_s, p.get("evidence"))
        seen[base] += 1
        items.append({
            "item_id": _item_id("h" if kind == "hazard" else "b", *base, seen[base]),
            "source": "scorer_events", "kind": kind, "k": p["k"], "t_s": t_s,
            "group": group, "name": name, "dimension": p.get("dimension"), "hazard": kind == "hazard" or bool(p.get("hazard")),
            "deterministic": p.get("deterministic"), "evidence": p.get("evidence"),
            "title": f"{group} {name}".strip(),
            "context": {"pass_id": p.get("pass_id"), "ts": e.get("ts"),
                        "cursor": {"k": p["k"], "t_s": t_s, "t_detected_s": p.get("t_detected_s")}},
        })
    items.sort(key=lambda i: (i["k"], i["t_s"] if isinstance(i["t_s"], (int, float)) else 0, i["item_id"]))
    _cache[f] = (sig, items)
    return items


def file_items(run_dir: Path) -> list[dict]:
    """Optional ``review-items.json``: ``{"items": [{"id", "title", "evidence", "group", "name", ...}]}``."""
    try:
        doc = json.loads((run_dir / "review-items.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for it in doc.get("items", []) if isinstance(doc, dict) else []:
        if not isinstance(it, dict) or not isinstance(it.get("id"), str):
            continue
        out.append({"item_id": "f-" + it["id"][:80], "source": "file", "kind": it.get("kind", "label"),
                    "k": it.get("k"), "t_s": it.get("t_s"), "group": it.get("group", ""), "name": it.get("name", ""),
                    "dimension": it.get("dimension"), "hazard": bool(it.get("hazard", False)),
                    "deterministic": it.get("deterministic"), "evidence": it.get("evidence"),
                    "title": it.get("title") or it["id"], "context": it.get("context") or {},
                    "proposed_label": it.get("proposed_label"), "draft_note": it.get("draft_note")})
    return out


SOURCES: dict[str, Source] = {"scorer_events": scorer_events, "file": file_items}


def _draft_labels(run_dir: Path) -> list[dict]:
    """Optional ``review-draft.json``: ``{"labels": [{"match": {"kind", "group", "name", "k"}, "proposed": "confirm",
    "note": "..."}]}``, proposed (draft) labels that are attached to matching items. They are suggestions only."""
    try:
        doc = json.loads((run_dir / "review-draft.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [x for x in doc.get("labels", []) if isinstance(x, dict) and isinstance(x.get("match"), dict)] \
        if isinstance(doc, dict) else []


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
    try:
        with open(review_path(run_dir), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and isinstance(rec.get("item_id"), str):
                    out.append(rec)
    except OSError:
        pass
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
