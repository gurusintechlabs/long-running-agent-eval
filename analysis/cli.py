"""``lrae ingest | dashboard | report`` handlers; runner/cli.py calls :func:`add_parsers`."""
from __future__ import annotations

from pathlib import Path

DEFAULT_RUNS = Path("runs")


def _db(a) -> Path:
    return Path(a.db) if a.db else DEFAULT_RUNS / "metrics.sqlite"


def _out(a) -> Path:
    return Path(a.out) if a.out else DEFAULT_RUNS / "reports" / a.experiment_id


def cmd_ingest(a) -> int:
    from analysis.ingest import ingest
    runs_dir = Path(a.runs_dir)
    db = Path(a.db) if a.db else runs_dir / "metrics.sqlite"
    rep = ingest(runs_dir, db)
    print(f"ingested {rep.runs} runs ({rep.in_survival} in survival set), {rep.checkpoints} checkpoints, "
          f"{rep.metrics} metrics, {rep.counters} counters, {rep.hazards} hazards, {rep.test_outcomes} test outcomes, {rep.stages} stages, "
          f"{rep.agent_test_runs} agent test runs -> {db}")
    for w in rep.warnings:
        print(f"warning: {w}")
    return 0


def cmd_dashboard(a) -> int:
    from report.dashboard import build_dashboard
    path = build_dashboard(_db(a), a.experiment_id, _out(a))
    print(path)
    return 0


def cmd_report(a) -> int:
    if not a.pdf:
        print("lrae report: pass --pdf")
        return 2
    from report.build import build_pdf
    print(build_pdf(_db(a), a.experiment_id, _out(a)))
    return 0


def add_parsers(sp) -> None:
    i = sp.add_parser("ingest", help="rebuild the metrics store from run artifacts")
    i.add_argument("runs_dir", nargs="?", default=str(DEFAULT_RUNS))
    i.add_argument("--db", default=None, help="default: <runs_dir>/metrics.sqlite")
    i.set_defaults(func=cmd_ingest)
    d = sp.add_parser("dashboard", help="build the static HTML dashboard")
    d.add_argument("experiment_id")
    d.add_argument("--db", default=None)
    d.add_argument("--out", default=None, help="default: runs/reports/<experiment_id>")
    d.set_defaults(func=cmd_dashboard)
    r = sp.add_parser("report", help="build the report")
    r.add_argument("experiment_id")
    r.add_argument("--pdf", action="store_true")
    r.add_argument("--db", default=None)
    r.add_argument("--out", default=None)
    r.set_defaults(func=cmd_report)
