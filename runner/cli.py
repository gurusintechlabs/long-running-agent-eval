"""``lrae`` command line (docs/spec.md §5.4)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from analysis import cli as analysis_cli
from runner import manifest as mf
from runner import memory
from runner.orchestrator import Run, RunState, recover_unfinalized
from runner.resume import parse_checkpoint, resume_run
from scorer import cli as scorer_cli
from spec.loader import REPO_ROOT, SpecError, load_spec


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lrae", description="Long-Running Agent Evaluation framework")
    # Testing overrides; they go before the subcommand.
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--claude-home", type=Path, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--home", type=Path, default=None, help=argparse.SUPPRESS)
    sp = ap.add_subparsers(dest="cmd", required=True)

    v = sp.add_parser("validate", help="validate a spec and print its hash and run IDs")
    v.add_argument("spec", type=Path)

    r = sp.add_parser("run", help="execute runs from a spec")
    r.add_argument("spec", type=Path)
    r.add_argument("--config", action="append", help="only this config (repeatable)")
    r.add_argument("--repeat", type=int, action="append", help="only this repeat index (repeatable)")
    r.add_argument("--confirm-spend", action="store_true",
                   help="required for the real agent: acknowledge that runs consume subscription usage")
    r.add_argument("--no-caffeinate", action="store_true")
    r.add_argument("--no-score", action="store_true", help="skip checkpoint scoring (score later)")

    rs = sp.add_parser("resume", help="resume a run from a snapshot")
    rs.add_argument("run_id")
    rs.add_argument("--from", dest="from_k", required=True, help="checkpoint, e.g. t2")
    rs.add_argument("--confirm-spend", action="store_true")
    rs.add_argument("--no-caffeinate", action="store_true")

    sp.add_parser("clean", help="finish cleanup of crashed runs and leftover agent state dirs")

    scorer_cli.add_parsers(sp)    # score, install-scorer
    analysis_cli.add_parsers(sp)  # ingest, dashboard, report
    return ap


def cmd_validate(a) -> int:
    loaded = load_spec(a.spec, repo_root=a.repo_root)
    s = loaded.spec
    print(f"experiment {s.experiment_id}  spec_hash {loaded.spec_hash}")
    print(f"agent {s.agent.runtime} model={s.agent.model} cli={s.agent.claude_code_version}")
    print(f"{s.run.checkpoint_count} checkpoints of {s.run.checkpoint_interval_min} min, work_dir {s.isolation.work_dir}")
    for cfg in s.run.configs:
        for rep in range(s.run.repeats):
            print("  " + loaded.run_id(cfg, rep))
    return 0


def cmd_run(a) -> int:
    loaded = load_spec(a.spec, repo_root=a.repo_root)
    s = loaded.spec
    if s.agent.runtime == "claude_code" and not a.confirm_spend:
        print("refusing to start real-agent runs without --confirm-spend "
              "(runs consume subscription usage; see docs/spec.md D-16)", file=sys.stderr)
        return 2
    for rid in recover_unfinalized(a.repo_root, a.claude_home):
        print(f"recovered crashed run {rid}")
    configs = a.config or s.run.configs
    repeats = a.repeat if a.repeat is not None else list(range(s.run.repeats))
    bad = 0
    for cfg in configs:
        for rep in repeats:
            spent = experiment_spend(a.repo_root, s.experiment_id, loaded.spec_hash)
            if spent >= s.budget.experiment_usd:
                print(f"experiment budget reached: ${spent:.2f} estimated of ${s.budget.experiment_usd:.2f}; "
                      "not starting more runs", file=sys.stderr)
                return 1
            run = Run(loaded, cfg, rep, repo_root=a.repo_root, claude_home=a.claude_home,
                      host_home=a.home, confirm_spend=a.confirm_spend, caffeinate=not a.no_caffeinate,
                      score=not a.no_score)
            res = run.execute()
            print(f"{res.run_id}: {res.state.value}" + (f"  ({res.error})" if res.error else ""), flush=True)
            bad += res.state != RunState.COMPLETED
    return 1 if bad else 0


def experiment_spend(repo_root: Path, experiment_id: str, spec_hash: str) -> float:
    """Estimated agent spend of finished runs of this experiment (same spec hash), from manifests."""
    total = 0.0
    for mpath in sorted((Path(repo_root) / "runs").glob("*/manifest.json")):
        try:
            m = mf.load(mpath)
        except (OSError, ValueError):
            continue
        if m.get("experiment_id") == experiment_id and m.get("spec_hash") == spec_hash:
            total += float((m.get("end") or {}).get("cost_usd") or 0)
    return total


def cmd_resume(a) -> int:
    res = resume_run(a.run_id, parse_checkpoint(a.from_k), repo_root=a.repo_root, claude_home=a.claude_home,
                     host_home=a.home, confirm_spend=a.confirm_spend, caffeinate=not a.no_caffeinate)
    print(f"{res.run_id}: {res.state.value}" + (f"  ({res.error})" if res.error else ""))
    return 0 if res.state == RunState.COMPLETED else 1


def cmd_clean(a) -> int:
    recovered = recover_unfinalized(a.repo_root, a.claude_home)
    for rid in recovered:
        print(f"recovered crashed run {rid}")
    workspaces = []
    for mpath in sorted((a.repo_root / "runs").glob("*/manifest.json")):
        try:
            m = mf.load(mpath)
        except (OSError, ValueError):
            continue
        if "end" in m and m.get("paths", {}).get("workspace"):
            workspaces.append(Path(m["paths"]["workspace"]))
    removed = memory.clean_workspaces(workspaces, a.claude_home)
    for r in removed:
        print(f"removed leftover agent state dir {r}")
    if not recovered and not removed:
        print("nothing to clean")
    return 0


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        if a.cmd == "validate":
            return cmd_validate(a)
        if a.cmd == "run":
            return cmd_run(a)
        if a.cmd == "resume":
            return cmd_resume(a)
        if a.cmd == "clean":
            return cmd_clean(a)
        if a.cmd == "score":
            return scorer_cli.cmd_score(a)
        if a.cmd == "install-scorer":
            return scorer_cli.cmd_install_scorer(a)
        return a.func(a)  # ingest, dashboard, report
    except (SpecError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
