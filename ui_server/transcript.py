"""Normalised transcript of ``agent_stream.jsonl`` (U3).

Built only from the *parsed* events the runner pump writes (docs/interfaces.md §2): ``assistant.text``,
``tool.call``, ``tool.result``, ``context.compaction``, ``agent.test_run``, ``session.init``,
``session.result`` and ``permission.denied``. The raw ``stream.*`` copies are skipped from their
envelope header, without parsing their (large) bodies, except that the ``stream.user`` message just
before a ``tool.result`` is remembered so the full result text can be fetched on demand.

The per-run item index is cached in memory (compact items, texts cut to ``KEEP_CHARS``) and extended
incrementally when the file grows.
"""
from __future__ import annotations

import json
import threading
from bisect import bisect_right
from collections import OrderedDict
from dataclasses import dataclass, field

from ui_server import eventlog as el

KEEP_CHARS = 4_000          # assistant text kept in the index
SUMMARY_CHARS = 200
RESULT_KEEP = 600
BLOB_CHARS = 2_000          # per item, searchable text
RESULT_FULL_CAP = 200_000
DEFAULT_LIMIT, MAX_LIMIT = 100, 500
KINDS = ("text", "tool", "compaction", "test_run", "session", "denied")
_WANTED = {"assistant.text": "text", "tool.call": "tool", "tool.result": "result",
           "context.compaction": "compaction", "agent.test_run": "test_run", "session.init": "session",
           "session.result": "session", "permission.denied": "denied"}


@dataclass
class TIndex:
    key: str
    sig: tuple = ()
    pos: int = 0
    items: list[dict] = field(default_factory=list)
    offs: list[int] = field(default_factory=list)
    pending: dict[str, dict] = field(default_factory=dict)
    prev: tuple[int, str] | None = None     # (start, type) of the previous line


_cache: OrderedDict[str, TIndex] = OrderedDict()
_lock = threading.Lock()


def _summary(tool: str | None, inp) -> str:
    if not isinstance(inp, dict):
        return ""
    for k in ("command", "file_path", "path", "notebook_path", "pattern", "query", "url", "prompt",
              "description"):
        v = inp.get(k)
        if isinstance(v, str) and v:
            if k in ("command", "prompt", "description"):
                v = v.strip().splitlines()[0] if v.strip() else v
            return v[:SUMMARY_CHARS]
    try:
        return json.dumps(inp, ensure_ascii=False, separators=(",", ":"))[:SUMMARY_CHARS]
    except (TypeError, ValueError):
        return ""


def _add(ix: TIndex, item: dict, blob: str) -> None:
    item["_blob"] = blob[:BLOB_CHARS].lower()
    ix.items.append(item)
    ix.offs.append(item["off"])


def _consume(ix: TIndex, start: int, raw: bytes | None, clocks) -> None:
    if raw is None:
        ix.prev = (start, "_oversized")
        return
    h = el.header(raw)
    typ = h[2] if h else "_bad"
    kind = _WANTED.get(typ)
    prev, ix.prev = ix.prev, (start, typ)
    if kind is None or h is None:
        return
    try:
        e = json.loads(raw)
    except ValueError:
        return
    p = e.get("payload") if isinstance(e, dict) else None
    if not isinstance(p, dict):
        return
    ts = e.get("ts")
    base = {"off": start, "seq": e.get("seq"), "ts": ts, "epoch": el.ts_epoch(ts), "t_s": None}
    t = el.run_time(ts, clocks)
    base["t_s"] = None if t is None else round(t, 3)
    if kind == "text":
        text = p.get("text") if isinstance(p.get("text"), str) else ""
        _add(ix, {**base, "kind": "text", "text": text[:KEEP_CHARS], "chars": len(text),
                  "text_truncated": bool(p.get("truncated")) or len(text) > KEEP_CHARS}, text)
    elif kind == "tool":
        tool = p.get("tool") if isinstance(p.get("tool"), str) else None
        s = _summary(tool, p.get("input"))
        item = {**base, "kind": "tool", "tool": tool, "tool_use_id": p.get("tool_use_id"),
                "input_summary": s, "input_truncated": bool(p.get("truncated")), "status": "pending",
                "result_off": None, "raw_off": None, "result_size": None, "result_tail": None,
                "dur_s": None}
        _add(ix, item, f"{tool} {s} {json.dumps(p.get('input'), ensure_ascii=False)[:BLOB_CHARS]}")
        if isinstance(p.get("tool_use_id"), str):
            ix.pending[p["tool_use_id"]] = item
    elif kind == "result":
        tail = p.get("text_tail") if isinstance(p.get("text_tail"), str) else ""
        item = ix.pending.pop(p.get("tool_use_id"), None) if isinstance(p.get("tool_use_id"), str) else None
        status = "error" if p.get("is_error") else "ok"
        raw_off = prev[0] if prev and prev[1] == "stream.user" else None
        if item is None:        # a result whose call is not in the log (resume, torn file)
            item = {**base, "kind": "tool", "tool": None, "tool_use_id": p.get("tool_use_id"),
                    "input_summary": "", "input_truncated": False, "status": status, "result_off": start,
                    "raw_off": raw_off, "result_size": p.get("size"), "result_tail": tail[-RESULT_KEEP:],
                    "dur_s": None}
            _add(ix, item, tail)
            return
        item.update(status=status, result_off=start, raw_off=raw_off, result_size=p.get("size"),
                    result_tail=tail[-RESULT_KEEP:])
        if base["epoch"] is not None and item["epoch"] is not None:
            item["dur_s"] = round(base["epoch"] - item["epoch"], 3)
        item["_blob"] = (item["_blob"] + " " + tail[-RESULT_KEEP:].lower())[:BLOB_CHARS * 2]
    elif kind == "compaction":
        _add(ix, {**base, "kind": "compaction", "trigger": p.get("trigger"), "pre_tokens": p.get("pre_tokens")},
             f"compaction {p.get('trigger')}")
    elif kind == "test_run":
        _add(ix, {**base, "kind": "test_run", "passed": p.get("passed"), "failed": p.get("failed"),
                  "errors": p.get("errors"), "skipped": p.get("skipped"), "raw_summary": p.get("raw_summary")},
             f"pytest {p.get('raw_summary')}")
    elif kind == "session":
        extra = ({"model": p.get("model")} if typ == "session.init" else
                 {"subtype": p.get("subtype"), "is_error": p.get("is_error"),
                  "total_cost_usd": p.get("total_cost_usd"), "num_turns": p.get("num_turns")})
        _add(ix, {**base, "kind": "session", "event": typ, "session_id": p.get("session_id"), **extra}, typ)
    elif kind == "denied":
        _add(ix, {**base, "kind": "denied", "tool": p.get("tool"),
                  "input_summary": _summary(p.get("tool"), p.get("input"))}, f"denied {p.get('tool')}")


def get_tindex(rl: el.RunLog) -> TIndex:
    path = rl.path("agent_stream")
    key = str(path)
    idx = el.get_index(path)        # also validates size/mtime and discovers run.clock via orchestrator
    sig = (idx.size, idx.mtime_ns, idx.ino)
    with _lock:
        ix = _cache.get(key)
        if ix is not None and ix.sig == sig:
            _cache.move_to_end(key)
            return ix
        if ix is None or ix.pos > idx.end or ix.sig[2] != idx.ino:
            ix = TIndex(key)
        clocks = rl.clocks()
        for start, nxt, raw in el.iter_lines(path, ix.pos):
            _consume(ix, start, raw, clocks)
            ix.pos = nxt
        ix.sig = sig
        _cache[key] = ix
        _cache.move_to_end(key)
        while len(_cache) > 16:
            _cache.popitem(last=False)
        return ix


def turns(rl: el.RunLog) -> list[dict]:
    """``[{turn, start_s, end_s, start_epoch, end_epoch, first, returncode}]`` from turn.start/turn.end."""
    out: list[dict] = []
    clocks = rl.clocks()
    for _s, _n, raw in el.iter_lines(rl.path("orchestrator")):
        if raw is None:
            continue
        h = el.header(raw)
        if h is None or h[2] not in ("turn.start", "turn.end"):
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        p = e.get("payload") or {}
        ep = el.ts_epoch(e.get("ts"))
        t = el.run_time(e.get("ts"), clocks)
        if h[2] == "turn.start":
            out.append({"turn": len(out) + 1, "start_s": t, "end_s": None, "start_epoch": ep, "end_epoch": None,
                        "first": bool(p.get("first")), "returncode": None})
        elif out:
            out[-1].update(end_s=t, end_epoch=ep, returncode=p.get("returncode"))
    return out


def _public(item: dict, turn: int | None, max_chars: int) -> dict:
    out = {k: v for k, v in item.items() if not k.startswith("_") and k not in ("off", "epoch", "raw_off",
                                                                              "result_off")}
    out["cursor"] = el.make_cursor("agent_stream", item["off"])
    out["turn"] = turn
    if item["kind"] == "text" and len(out["text"]) > max_chars:
        out["text"] = out["text"][:max_chars]
        out["text_truncated"] = True
    if item["kind"] == "tool":
        out["has_result"] = item["result_off"] is not None
        out["result_cursor"] = (el.make_cursor("agent_stream", item["result_off"])
                                if item["result_off"] is not None else None)
    return out


def _turn_of(starts: list[float], item: dict) -> int | None:
    if not starts or item["epoch"] is None:
        return None
    return max(1, bisect_right(starts, item["epoch"] + 1e-6))


def query(rl: el.RunLog, *, after: str | None, limit: int, tools: list[str], kinds: list[str], q: str | None,
          errors_only: bool, turn: int | None, around: str | None, around_seq: int | None,
          around_t_s: float | None, ctx_before: int, ctx_after: int, max_chars: int) -> dict:
    ix = get_tindex(rl)
    tl = turns(rl)
    starts = [t["start_epoch"] for t in tl if t["start_epoch"] is not None]
    qb = q.lower() if q else None
    toolset, kindset = set(tools), set(kinds)

    def keep(it: dict) -> bool:
        if kindset and it["kind"] not in kindset:
            return False
        if toolset and not (it["kind"] in ("tool", "denied") and it.get("tool") in toolset):
            return False
        if errors_only and not (it["kind"] == "tool" and it["status"] == "error"):
            return False
        if turn is not None and _turn_of(starts, it) != turn:
            return False
        return qb is None or qb in it["_blob"]

    n = len(ix.items)
    lo, hi = 0, n          # window of the item list to emit from
    mode = "page"
    if around or around_seq is not None or around_t_s is not None:
        mode = "around"
        if around:
            src, off = el.parse_cursor(around)
            if src != "agent_stream":
                raise el.CursorError("cursor belongs to another source")
            i = bisect_right(ix.offs, off) - 1
            if i < 0 or ix.offs[i] != off:
                i = max(0, bisect_right(ix.offs, off) - 1) if ix.offs else 0
        elif around_seq is not None:
            i = _nearest(ix.items, lambda it: it["seq"] if isinstance(it["seq"], int) else -1, around_seq)
        else:
            tgt = rl.epoch_of_t(around_t_s)
            i = 0 if tgt is None else _nearest(ix.items, lambda it: it["epoch"] or 0.0, tgt)
        lo, hi = max(0, i - ctx_before), min(n, i + ctx_after + 1)
        sel = [it for it in ix.items[lo:hi] if keep(it)]
        nxt, eof = None, True
        anchor = el.make_cursor("agent_stream", ix.items[i]["off"]) if ix.items else None
    else:
        start = 0
        if after:
            src, off = el.parse_cursor(after)
            if src != "agent_stream":
                raise el.CursorError("cursor belongs to another source")
            start = bisect_right(ix.offs, off)
        sel = []
        j = start
        while j < n and len(sel) < limit:
            if keep(ix.items[j]):
                sel.append(ix.items[j])
            j += 1
        eof = j >= n
        nxt = el.make_cursor("agent_stream", sel[-1]["off"]) if sel else after
        if eof and not sel and not after:
            nxt = None
        anchor = None
    facets: dict[str, dict] = {}
    for it in ix.items:
        if it["kind"] == "tool":
            f = facets.setdefault(it["tool"] or "(unknown)", {"tool": it["tool"], "count": 0, "errors": 0})
            f["count"] += 1
            f["errors"] += it["status"] == "error"
    return {"mode": mode, "anchor": anchor, "items": [_public(it, _turn_of(starts, it), max_chars) for it in sel],
            "next": nxt, "eof": eof, "total_items": n,
            "turns": [{k: (round(v, 3) if isinstance(v, float) and k.endswith("_s") else v)
                       for k, v in t.items() if not k.endswith("_epoch")} for t in tl],
            "tools": sorted(facets.values(), key=lambda f: -f["count"]),
            "indexed_bytes": ix.pos}


def _nearest(items: list[dict], key, target) -> int:
    best, bd = 0, None
    for i, it in enumerate(items):
        d = abs(key(it) - target)
        if bd is None or d < bd:
            best, bd = i, d
        elif key(it) > target:
            break
    return best


def item_detail(rl: el.RunLog, cursor: str) -> dict | None:
    """Full call/result of the transcript item that starts at ``cursor``."""
    src, off = el.parse_cursor(cursor)
    if src != "agent_stream":
        raise el.CursorError("cursor belongs to another source")
    ix = get_tindex(rl)
    i = bisect_right(ix.offs, off) - 1
    if i < 0 or ix.offs[i] != off:
        return None
    it = ix.items[i]
    ev = el.read_one(rl, cursor, full=True)
    out = {"item": _public(it, None, KEEP_CHARS), "event": ev}
    if it["kind"] == "tool":
        out["result_event"] = (el.read_one(rl, el.make_cursor("agent_stream", it["result_off"]), full=True)
                               if it["result_off"] is not None else None)
        out["result_text"], out["result_text_truncated"] = _raw_result(rl, it)
    return out


def _raw_result(rl: el.RunLog, it: dict) -> tuple[str | None, bool]:
    """Full text of the tool result from the raw ``stream.user`` message (capped)."""
    if it.get("raw_off") is None:
        return None, False
    ev = el.read_one(rl, el.make_cursor("agent_stream", it["raw_off"]), full=True, max_chars=RESULT_FULL_CAP)
    if not ev or not isinstance(ev.get("payload"), dict):
        return None, False
    content = ((ev["payload"].get("message") or {}).get("content")) or []
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") == it["tool_use_id"]:
            c = b.get("content")
            text = c if isinstance(c, str) else "\n".join(
                x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else ""
            return text[:RESULT_FULL_CAP], len(text) > RESULT_FULL_CAP or "…[truncated" in text
    return None, False
