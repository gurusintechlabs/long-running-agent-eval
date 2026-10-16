"""``lrae score`` and ``lrae install-scorer`` (hooked into runner/cli.py by the lead).

    lrae score <run_id> [--checkpoint K]
    lrae score --snapshot fixtures/snapshots/known_bad [--spec SPEC]
    lrae install-scorer [--spec SPEC]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from spec.loader import REPO_ROOT, load_spec

DEFAULT_SPEC = REPO_ROOT / "spec" / "examples" / "pilot.yaml"


def add_parsers(subparsers) -> None:
    s = subparsers.add_parser("score", help="score checkpoints of a run, or a plain snapshot dir")
    s.add_argument("run_id", nargs="?")
    s.add_argument("--checkpoint", type=int, default=None, help="only this checkpoint (default: all)")
    s.add_argument("--snapshot", type=Path, default=None,
                   help="score a working copy / fixtures/snapshots/<name> as checkpoint 1")
    s.add_argument("--spec", type=Path, default=None)
    s.add_argument("--check-determinism", action="store_true",
                   help="after re-scoring, compare with the previous pass of each checkpoint")
    s.add_argument("--confirm-spend", action="store_true",
                   help="allow the real claude_code judge (consumes subscription usage)")
    i = subparsers.add_parser("install-scorer", help="build tools/scorer-venv")
    i.add_argument("--spec", type=Path, default=None)
    i.add_argument("--force", action="store_true")


def _repo_root(args) -> Path:
    return Path(getattr(args, "repo_root", None) or REPO_ROOT)


def cmd_install_scorer(args) -> int:
    from scorer.venv import install_scorer
    root = _repo_root(args)
    spec = load_spec(args.spec or DEFAULT_SPEC, repo_root=root)
    py = install_scorer(root, Path(spec.spec.task.seed_requirements_lock),
                        force=getattr(args, "force", False))
    print(f"scorer venv ready: {py}")
    return 0


def _print(score) -> None:
    vals = {n: m["value"] for n, m in score.metrics.items()}
    print(f"checkpoint {score.k}: {'ok' if score.ok else 'FAILED'} in {score.duration_s:.1f}s"
          + (f"  error: {score.error}" if score.error else ""))
    print(json.dumps(vals, indent=1))
    for h in score.hazards:
        print(f"  hazard {h['dimension']}: {h['rule']} t_attr={h['t_attributed_s']:.1f}s")


def cmd_score(args) -> int:
    if getattr(args, "confirm_spend", False):
        os.environ["LRAE_CONFIRM_SPEND"] = "1"
    from scorer.venv import install_scorer
    root = _repo_root(args)
    if args.snapshot is not None:
        from scorer.standalone import score_snapshot_dir
        spec = load_spec(args.spec or DEFAULT_SPEC, repo_root=root)
        py = install_scorer(root, Path(spec.spec.task.seed_requirements_lock))
        out = root / "runs" / f"snapshot-{Path(args.snapshot).name}-{int(time.time())}"
        score = score_snapshot_dir(args.snapshot, spec, out, scorer_python=py, repo_root=root)
        _print(score)
        print(f"artifact: {out}")
        return 0 if score.ok else 1
    if not args.run_id:
        print("error: give a run_id or --snapshot", file=sys.stderr)
        return 2
    from scorer.run_checkpoint import Artifact, score_checkpoint
    art = root / "runs" / args.run_id
    if not art.is_dir():
        print(f"error: no such run: {art}", file=sys.stderr)
        return 1
    manifest = Artifact(art).manifest
    spec = load_spec(args.spec or manifest.get("spec_path") or DEFAULT_SPEC, repo_root=root)
    py = install_scorer(root, Path(spec.spec.task.seed_requirements_lock))
    ks = ([args.checkpoint] if args.checkpoint else
          sorted(int(p.name[1:]) for p in (art / "snapshots").glob("t*") if p.name[1:].isdigit()))
    bad = 0
    for k in ks:
        score = score_checkpoint(art, k, spec=spec, scorer_python=py)
        _print(score)
        bad += not score.ok
    if getattr(args, "check_determinism", False):
        from scorer.determinism import compare_last_two
        diffs = {k: d for k, d in compare_last_two(art).items() if k in ks}
        print("determinism: " + ("identical to the previous pass at every checkpoint" if not diffs
                                 else json.dumps(diffs, default=str)))
        bad += bool(diffs)
    return 1 if bad else 0
