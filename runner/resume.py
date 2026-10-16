"""Resume a run from a snapshot (docs/spec.md §5.2). Used to recover from host failures."""
from __future__ import annotations

import re
from pathlib import Path

from runner import manifest as mf
from runner.orchestrator import Run, RunResult, _pid_alive, recover_unfinalized
from spec.loader import REPO_ROOT, SpecError, load_spec


def parse_checkpoint(text: str) -> int:
    m = re.fullmatch(r"t?(\d+)", text.strip())
    if not m or int(m.group(1)) < 1:
        raise ValueError(f"bad checkpoint {text!r}; use e.g. t2")
    return int(m.group(1))


def resume_run(run_id: str, from_k: int, *, repo_root: Path = REPO_ROOT, claude_home: Path | None = None,
               host_home: Path | None = None, confirm_spend: bool = False, caffeinate: bool = True,
               score: bool = False) -> RunResult:
    repo_root = Path(repo_root)
    mpath = repo_root / "runs" / run_id / "manifest.json"
    if not mpath.exists():
        raise SpecError(f"no such run: {run_id}")
    recover_unfinalized(repo_root, claude_home)  # kills orphans, deletes leftovers of a crashed run
    m = mf.load(mpath)
    if _pid_alive(m.get("harness_pid")) and "end" not in m:
        raise SpecError(f"run {run_id} is still being driven by pid {m['harness_pid']}")
    loaded = load_spec(m["spec_path"], repo_root=repo_root)
    if loaded.spec_hash != m["spec_hash"]:
        raise SpecError("spec or a referenced file changed since the run started "
                        f"({loaded.spec_hash[:8]} != {m['spec_hash'][:8]}); refusing to resume")
    run = Run(loaded, m["config"], m["repeat"], repo_root=repo_root, claude_home=claude_home,
              host_home=host_home, resume_from=from_k, confirm_spend=confirm_spend, caffeinate=caffeinate,
              score=score)
    return run.execute()
