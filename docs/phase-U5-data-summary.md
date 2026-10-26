# Phase U5 (backend) summary: control with the spend gate

Branch `ui-u5-control` (from `ui-manager` 9d8da0c). API reference: `docs/ui-api-control.md`. No API spend, `claude` never run, no `api` test run, no claude_code run started (the spend-gate tests use a fake spawner).

## Built
- `ui_server/control_core.py`: spec path allowlist, estimate computed from the loaded spec, single-use nonce store, harness process verification, minimal env builder, exclusive launcher (mutex + flock), signal handling.
- `ui_server/routes/control.py` (auto-discovered): `POST /api/launch/preview`, `/api/launch`, `/api/runs/{id}/resume/preview`, `/api/runs/{id}/resume`, `/stop`, `/kill`, `/score`, `/api/clean`, `GET /api/control/state`.
- Tests: `tests/unit/ui_server/test_control.py` (76, fast, fake spawner), `test_control_e2e.py` (2, `local`, real `lrae` subprocess, scripted runtime, about 10 s), helpers in `control_support.py`. No existing file changed.

## Tested (security properties)
- Every POST: 401 without or with a wrong token, 403 with a foreign Origin or Host, and nothing spawned.
- Spend gate: no/garbage/empty nonce never spawns; wrong, expired, reused nonce rejected; nonce of the wrong kind or for another run/checkpoint rejected; editing the spec or a referenced file between preview and launch (or deleting the spec) gives 409 and burns the nonce; client cannot inject any estimate figure (unknown fields 422); claude_code spec with missing/wrong `confirm_usd`/`confirm_runs` is rejected and the subprocess is never started, three misses burn the nonce; confirmed path passes `--confirm-spend` exactly once; scripted launches never carry it, even if the client sends confirmation fields; a `claude_code` judge on a scripted agent counts as real spend; same for resume.
- One run at a time: second launch while active is 409 and keeps its nonce; six simultaneous launches with distinct nonces start exactly one; four simultaneous with the same nonce start exactly one; a live lookalike harness in a manifest blocks launch; a stale/foreign pid does not; a second UI process is excluded by the flock.
- Path allowlist: traversal, absolute paths, symlink out of `spec/`, wrong suffix, NUL, over-long, `~`, bad draft names, both/neither ref.
- Env: with fake `ANTHROPIC_API_KEY`, `AWS_*`, `GITHUB_TOKEN`, `LRAE_CONFIRM_SPEND`, `PYTHONPATH`, `LD_PRELOAD`, etc. in the server's environment, the subprocess env is a subset of the allowlist; `build_env` refuses secret-looking extras. Logs land in `ui_state/`, not in the work dir.
- Signals: a decoy sleeper in a manifest (plain, with the words `lrae`/`runner.cli`/`run` in a `-c` program or a bash `$0`), the server's own pid, pid 1, non-integer pids, a lookalike started after the run, and an ended run are never signalled (spy on `os.kill`, decoy stays alive). A verified harness gets SIGINT once (second stop 409) or, with `confirm` equal to the run id, SIGKILL followed by `lrae clean`.
- End to end (real CLI, scripted): preview, launch (manifest seen, state active), second launch refused, stop at t2 (end state FAILED, work dir, agent processes and state dir gone), resume from t2 completes with COMPLETED and all four snapshots; hard kill then clean leaves `INTERRUPTED` with `recovered`.

Commands (worktree root, venv python): `python -m pytest tests/unit/ui_server` (155 passed), `python -m pytest tests/unit/ui_server -m local` (2 passed), `ruff check ui_server tests/unit/ui_server` clean. I verified `ui_server.__file__` resolves into the worktree.

## Deviations and decisions to confirm
1. `LRAE_CONFIRM_SPEND` is never set in the subprocess env, only the `--confirm-spend` flag (the harness derives the variable for its own scorer subprocess). Stricter than the brief; one channel to audit.
2. Stop = SIGINT and the resulting state is `FAILED` (that is what the runner does for an unhandled KeyboardInterrupt), not `INTERRUPTED`. A clean "stopped by user" end state would need a runner change (a SIGINT handler setting `final_state`/`censored_reason`); not made because `runner/` is out of scope. Owner decision.
3. Re-scoring with a `claude_code` judge is refused from the UI (409 `judge_spends`) rather than offering a nonce flow. Scripted-judge re-scoring spends nothing (verified in `scorer/metrics/x_judge.py`: the real judge raises `SpendNotConfirmed` without the flag).
4. The typed confirmation is `confirm_usd` (= `min(experiment_usd, runs x per_run_usd)`) plus `confirm_runs`; the brief's optional `confirm_text` is not used.
5. A manifest whose pid is alive but is not an `lrae` process is treated as stale (does not block launches). The runner's own `recover_unfinalized` still uses a bare `pid_exists`, so it may skip such a run; harmless.
6. Preview does not run `claude --version` (L-6) because that executes `claude`; it only checks that the binary is on PATH. L-6 and the probe run inside the harness.
7. Resume refuses (422/403) when the manifest's `spec_path` is outside `spec/`, so runs started from a spec elsewhere must be resumed from the terminal.
8. Launch and resume use the CLI's defaults (scoring on, caffeinate on). Tests pass `--no-score --no-caffeinate` through `ControlConfig.run_argv`.

## Residual risks
- The nonce proves "the same spec, seen by the same token holder"; the typed figures are friction, not authentication. Anyone with the token can preview and launch. The token is the real boundary.
- TOCTOU: the CLI reloads the spec a few ms after our check. The server compares the manifest's `spec_hash` with the bound hash afterwards and SIGINTs the run on mismatch, but a swap in that window with a still-valid hash is not possible; a swap is detected, not prevented.
- Nonces live in memory: a server restart loses them (safe direction). A tracked child is forgotten on restart; `harness_pid` in the manifest still blocks launches after the manifest appears. The window between spawn and manifest write during a UI restart is a few seconds.
- After SIGINT, queued checkpoint scoring is drained; with a real judge that can still spend after the user pressed stop.
- `kill` runs a global `lrae clean`, which also recovers other crashed runs.
- First real UI launch of a `claude_code` spec is untested by design; the owner must approve the spend and do it deliberately.
- Specs referencing `spec/drafts/` depend on the drafts agent's convention (`spec/drafts/<name>.yaml`, inside `spec/` so the allowlist already covers it).
