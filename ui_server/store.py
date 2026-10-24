"""Reading runs: manifests and orchestrator logs on disk (always current), enriched from the
read-only ``metrics.sqlite`` cache when a run has been ingested (UI-8)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

import psutil

from ui_server.safety import resolve_run_dir

MANIFEST_KEYS = ("run_id", "experiment_id", "config", "repeat", "model", "runtime", "spec_hash",
                 "claude_code_version", "seed_commit", "isolation_mode", "safe_mode", "framework", "host",
                 "policy_sha256", "resumed", "start_epoch", "end", "spec")


def open_ro(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    con = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, check_same_thread=False)
    con.execute("PRAGMA query_only = ON")
    con.row_factory = sqlite3.Row
    return con


def read_json(path: Path) -> dict | None:
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def read_jsonl(path: Path) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue  # blank or torn (a line still being written)
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out


def pid_alive(pid) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except (psutil.Error, OverflowError, ValueError, OSError):
        return False


def orchestrator_info(run_dir: Path) -> dict:
    """``{"state": last state entered, "checkpoints": {k: payload}}`` from events/orchestrator.jsonl."""
    state, cps = None, {}
    for ev in read_jsonl(run_dir / "events" / "orchestrator.jsonl"):
        p = ev.get("payload") or {}
        if ev.get("type") == "state" and isinstance(p.get("to"), str):
            state = p["to"]
        elif ev.get("type") == "checkpoint" and isinstance(p.get("k"), int):
            cps[p["k"]] = p  # a resumed run re-takes checkpoints: the last one wins
    return {"state": state, "checkpoints": cps}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def db_runs(con: sqlite3.Connection | None) -> dict[str, dict]:
    if con is None:
        return {}
    out = {r["run_id"]: dict(r) for r in con.execute("SELECT * FROM runs")}
    for rid, n in con.execute("SELECT run_id, COUNT(*) FROM hazards GROUP BY run_id"):
        out.setdefault(rid, {})["hazard_count"] = n
    return out


def run_summary(run_dir: Path, mf: dict, db_row: dict | None) -> dict:
    end = mf.get("end") if isinstance(mf.get("end"), dict) else None
    info = orchestrator_info(run_dir)
    live = end is None and pid_alive(mf.get("harness_pid"))
    state = end.get("state") if end else (info["state"] if live else "UNFINISHED")
    ingested = db_row is not None
    row = db_row or {}
    cost = _num((end or {}).get("cost_usd"))
    tokens = (end or {}).get("tokens")
    return {
        "run_id": mf.get("run_id") or run_dir.name,
        "experiment_id": mf.get("experiment_id"),
        "config": mf.get("config"), "repeat": mf.get("repeat"),
        "model": mf.get("model"), "claude_code_version": mf.get("claude_code_version"),
        "isolation_mode": mf.get("isolation_mode"), "runtime": mf.get("runtime"),
        "state": state, "live": live, "resumed": bool(mf.get("resumed")),
        "start_epoch": _num(mf.get("original_start_epoch")) or _num(mf.get("start_epoch")),
        "end_epoch": _num((end or {}).get("end_epoch")),
        "checkpoints": (end or {}).get("checkpoints") if isinstance((end or {}).get("checkpoints"), int)
        else len(info["checkpoints"]),
        "cost_usd": cost if cost is not None else _num(row.get("cost_usd")) if ingested else None,
        "tokens": tokens if isinstance(tokens, int) else row.get("tokens") if ingested else None,
        "ingested": ingested,
        "duration_s": _num(row.get("duration_s")) if ingested else None,
        "ttfh_s": _num(row.get("ttfh_s")) if ingested else None,
        "hazard_count": (row.get("hazard_count") or 0) if ingested else None,
        "censored_reason": row.get("censored_reason") if ingested else None,
    }


def list_runs(runs_dir: Path, con: sqlite3.Connection | None) -> list[dict]:
    db = db_runs(con)
    out = []
    try:
        names = sorted(p.name for p in runs_dir.iterdir())
    except OSError:
        return []
    for name in names:
        d = resolve_run_dir(runs_dir, name)
        mf = read_json(d / "manifest.json") if d else None
        if mf is None:
            continue
        s = run_summary(d, mf, db.get(mf.get("run_id") or name))
        out.append(s)
    out.sort(key=lambda r: (-(r["start_epoch"] or 0), r["run_id"]))
    return out


def run_detail_manifest(mf: dict) -> dict:
    return {k: mf[k] for k in MANIFEST_KEYS if k in mf}


def hazards(con: sqlite3.Connection | None, rid: str) -> list[dict]:
    if con is None:
        return []
    cur = con.execute("SELECT dimension, rule, t_attributed_s, t_detected_s, k, evidence FROM hazards "
                      "WHERE run_id = ? ORDER BY t_attributed_s, dimension", (rid,))
    return [dict(r) for r in cur]


def checkpoints(run_dir: Path, con: sqlite3.Connection | None, rid: str) -> tuple[bool, list[dict]]:
    """``(ingested, rows)``: checkpoints from the orchestrator log, each with its stored metrics."""
    cps = orchestrator_info(run_dir)["checkpoints"]
    ingested = bool(con is not None and con.execute("SELECT 1 FROM runs WHERE run_id = ?", (rid,)).fetchone())
    metrics: dict[int, dict] = {}
    if ingested:
        for r in con.execute("SELECT k, name, value FROM metrics WHERE run_id = ?", (rid,)):
            metrics.setdefault(r["k"], {})[r["name"]] = r["value"]
    rows = [{"k": k, "t_s": _num(p.get("t_s")), "head_sha": p.get("head_sha"), "dirty": p.get("dirty"),
             "pause_ms": _num(p.get("pause_ms")), "metrics": metrics.get(k, {})}
            for k, p in sorted(cps.items())]
    return ingested, rows


def ingest_status(runs_dir: Path, con: sqlite3.Connection | None, db_path: Path) -> dict:
    runs = list_runs(runs_dir, con)
    on_disk = [r["run_id"] for r in runs]
    in_store = [r["run_id"] for r in runs if r["ingested"]]
    missing = [r for r in on_disk if r not in set(in_store)]
    newest = 0.0
    for r in on_disk:
        d = runs_dir / r
        for f in [d / "manifest.json", *(d / "events").glob("*.jsonl")]:
            try:
                newest = max(newest, f.stat().st_mtime)
            except OSError:
                pass
    exists = db_path.is_file()
    store_epoch = db_path.stat().st_mtime if exists else None
    reason = None
    if not exists:
        reason = "no metrics store yet"
    elif missing:
        reason = f"{len(missing)} run(s) are not in the store"
    elif store_epoch is not None and newest > store_epoch:
        reason = "run logs are newer than the store"
    return {"store_exists": exists, "stale": reason is not None, "reason": reason,
            "runs_on_disk": len(on_disk), "runs_in_store": len(in_store), "missing_from_store": missing,
            "store_epoch": store_epoch, "newest_log_epoch": newest or None}


def experiments(runs: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in runs:
        eid = r["experiment_id"] or "(unknown)"
        g = groups.setdefault(eid, {"experiment_id": eid, "runs": 0, "states": {}, "cost_usd": 0.0,
                                    "last_start_epoch": None, "live": False})
        g["runs"] += 1
        g["states"][r["state"]] = g["states"].get(r["state"], 0) + 1
        g["cost_usd"] += r["cost_usd"] or 0.0
        g["live"] = g["live"] or r["live"]
        if r["start_epoch"] and (g["last_start_epoch"] is None or r["start_epoch"] > g["last_start_epoch"]):
            g["last_start_epoch"] = r["start_epoch"]
    return sorted(groups.values(), key=lambda g: -(g["last_start_epoch"] or 0))
