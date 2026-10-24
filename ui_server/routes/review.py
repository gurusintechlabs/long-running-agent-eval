"""Label review API (phase U6, docs/ui-api-specs.md). The only file written under ``runs/`` is
``<run_id>/review.jsonl``, append-only."""
from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from ui_server import review_store as rs
from ui_server import safefs
from ui_server.deps import run_dir_or_404
from ui_server.safety import valid_run_id
from ui_server.settings import Settings


class DecisionBody(BaseModel):
    run_id: str
    item_id: str = Field(max_length=200)
    decision: Literal["confirm", "reject", "unsure"]
    note: str | None = Field(None, max_length=rs.NOTE_MAX)


class BatchItem(BaseModel):
    item_id: str = Field(max_length=200)
    decision: Literal["confirm", "reject", "unsure"]
    note: str | None = Field(None, max_length=rs.NOTE_MAX)


class BatchBody(BaseModel):
    run_id: str
    decisions: list[BatchItem] = Field(max_length=rs.BATCH_MAX)


def register(app: FastAPI, settings: Settings) -> None:
    def review_runs() -> list[str]:
        out = []
        try:
            entries = sorted(settings.runs_dir.iterdir())
        except OSError:
            return out
        for d in entries:
            if not d.is_symlink() and d.is_dir() and valid_run_id(d.name) and (
                    safefs.is_file(d / "events" / "scorer.jsonl") or safefs.is_file(d / "review-items.json")
                    or safefs.is_file(d / rs.REVIEW_FILE)):
                out.append(d.name)
        return out

    def view(item: dict, cur: dict[str, dict], hist: dict[str, int]) -> dict:
        d = cur.get(item["item_id"])
        return {**item, "decision": d, "status": d["decision"] if d else "pending",
                "history_count": hist.get(item["item_id"], 0)}

    @app.get("/api/review/runs")
    def runs():
        out = []
        for rid in review_runs():
            try:
                d = run_dir_or_404(settings, rid)
                items = rs.run_items(d)
                out.append({"run_id": rid, "items": len(items), **rs.counts(items, rs.latest(rs.read_history(d)))})
            except Exception as exc:  # noqa: BLE001  one malformed run must not hide the others
                out.append({"run_id": rid, "items": 0, "error": f"{type(exc).__name__}"})
        return {"runs": out}

    @app.get("/api/review/queue")
    def queue(run_id: str | None = None,
              status: Literal["pending", "confirm", "reject", "unsure", "reviewed", "all"] = "pending",
              kind: str | None = Query(None, max_length=40),
              limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
        rids = [run_id] if run_id else review_runs()
        items: list[dict] = []
        totals = {"pending": 0, "confirm": 0, "reject": 0, "unsure": 0}
        errors: dict[str, str] = {}
        for rid in rids:
            d = run_dir_or_404(settings, rid)
            try:
                hist_list = rs.read_history(d)
                cur = rs.latest(hist_list)
                hist: dict[str, int] = {}
                for h in hist_list:
                    hist[h["item_id"]] = hist.get(h["item_id"], 0) + 1
                run_views = []
                for it in rs.run_items(d):
                    if kind and it.get("kind") != kind:
                        continue
                    run_views.append(view(it, cur, hist))
            except Exception as exc:  # noqa: BLE001  isolate failures per run
                if run_id:
                    raise
                errors[rid] = type(exc).__name__
                continue
            for v in run_views:
                totals[v["status"]] += 1
                if status == "all" or v["status"] == status or (status == "reviewed" and v["status"] != "pending"):
                    items.append(v)
        out = {"items": items[offset:offset + limit], "total": len(items), "offset": offset, "counts": totals}
        if errors:
            out["errors"] = errors
        return out

    @app.post("/api/review/decision")
    def decision(body: DecisionBody):
        d = run_dir_or_404(settings, body.run_id)
        try:
            (rec,) = rs.append_decisions(d, [body.model_dump()])
        except rs.ReviewError as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        return {"ok": True, "decision": rec}

    @app.post("/api/review/decisions")
    def decisions(body: BatchBody):
        d = run_dir_or_404(settings, body.run_id)
        try:
            recs = rs.append_decisions(d, [x.model_dump() for x in body.decisions])
        except rs.ReviewError as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        return {"ok": True, "appended": len(recs), "decisions": recs}

    @app.get("/api/review/history")
    def history(run_id: str, item_id: str | None = Query(None, max_length=200)):
        d = run_dir_or_404(settings, run_id)
        h = rs.read_history(d)
        if item_id:
            h = [x for x in h if x["item_id"] == item_id]
        return {"run_id": run_id, "history": h}
