# UI control API (phase U5 backend)

All endpoints are under `/api`, JSON, and sit behind the global guards: `X-LRAE-Token` (or Bearer) on every request, `Host` must be `127.0.0.1|localhost|[::1]:<port>`, and any `Origin` header must be one of those origins. Errors from this module have the shape

```json
{"detail": {"code": "nonce_invalid", "message": "unknown confirmation nonce; preview first", "...extra": "..."}}
```

(`detail` is a plain string for generic FastAPI errors such as 401/404/422-validation.) Code: `ui_server/control_core.py` (logic), `ui_server/routes/control.py` (HTTP).

## Rules the UI must respect

1. Every number shown in the confirmation dialog comes from `POST .../preview`. The client sends no figures except the typed confirmation it echoes back.
2. A launch needs the nonce from the preview of the same spec and selection. Editing the spec file (or any file it references) after the preview invalidates the nonce (409 `spec_changed`, nonce burned, preview again).
3. `real_spend: true` (agent runtime `claude_code`, or a `claude_code` judge) additionally needs `confirm_usd` and `confirm_runs` equal to `confirmation.fields` of the preview. `--confirm-spend` is added to the `lrae` argv on that path only. For `scripted` specs nothing is typed, but the nonce is still required.
4. One run at a time: while any harness is alive, launch/resume/score/clean answer 409 `run_active`.
5. The spec may only be named by `spec_path` (relative to the repo root, or absolute) that resolves to a `.yaml` file inside `spec/` (this includes `spec/drafts/`), or by `draft` (a bare file name that maps to `spec/drafts/<name>`). Nothing else is accepted.

## Nonce flow

```
UI                                   server (Control)                           lrae CLI
 | POST /api/launch/preview            |                                          |
 |  {spec_path|draft, config?, repeat?}|  resolve path (allowlist) -> load_spec   |
 |                                     |  (same code as `lrae validate`)          |
 |                                     |  estimate from the spec, conflicts, checks
 |                                     |  nonce = token_urlsafe(32), TTL 300 s,   |
 |  <- estimate, checks, nonce         |  bound to the whole estimate + spec file |
 |                                     |                                          |
 | user reads the figures; for real spend types confirm_usd and confirm_runs      |
 |                                     |                                          |
 | POST /api/launch                    |                                          |
 |  {nonce, confirm_usd?, confirm_runs?}  1 nonce known, right kind, unexpired    |
 |                                     |  2 re-load spec, recompute estimate,     |
 |                                     |    equal to the bound one? else burn+409 |
 |                                     |  3 real spend: typed values match? else  |
 |                                     |    422 (3 misses burn the nonce)         |
 |                                     |  4 take start lock (mutex + flock)       |
 |                                     |  5 nothing alive? else 409, nonce kept   |
 |                                     |  6 consume nonce (single use)            |
 |                                     |  7 spawn detached: python -m runner.cli  |
 |                                     |      --repo-root R run SPEC --config ... |-->
 |                                     |      --repeat ... [--confirm-spend]      |
 |  <- 200 {run_id, pid, run_ids}      |  8 wait (<= 30 s) for the manifest       |
 |     (202 if the manifest is not up) |    check its spec_hash == the bound one  |
```

Nonce errors: `400 nonce_invalid` (unknown, expired, already used, wrong kind, or invalidated), `409 spec_changed`, `422 confirmation_mismatch`, `409 run_active`, `409 busy` (another start in progress).

## Endpoints

### POST /api/launch/preview
Request: `{"spec_path": "spec/examples/pilot-scripted.yaml"}` or `{"draft": "mine.yaml"}`, optional `"config": "A"` (or a list) and `"repeat": 0` (or a list of indices). Unknown fields are rejected (422). Errors: 403 `spec_not_allowed`, 404 `spec_not_found`, 422 `bad_spec_ref|spec_invalid|bad_selection`.

```json
{
  "estimate": {
    "kind": "launch", "spec_path": "spec/examples/pilot-scripted.yaml", "experiment_id": "pilot-export-csv-scripted",
    "spec_hash": "def6...", "runtime": "scripted", "model": null, "claude_code_version": "n/a",
    "judge_runtime": "scripted", "judge_model": "claude-opus-5-5",
    "real_spend": false, "spend_reasons": [],
    "configs": ["A"], "repeats": [0, 1], "run_ids": ["pilot-export-csv-scripted-A-r00-def6afaa", "...-r01-..."], "run_count": 2,
    "per_run_usd": 1.0, "per_run_tokens": null, "experiment_usd": 5.0, "max_spend_usd": 2.0,
    "spent_so_far_usd": 0.0,
    "duration_min": 6.0, "checkpoint_interval_min": 1.0, "checkpoint_count": 6, "max_wall_clock_min": 12.0
  },
  "checks": [{"name": "spec validates (lrae validate)", "ok": true, "detail": "def6afaad595"},
             {"name": "no existing run folder for these run ids", "ok": true, "detail": ""}],
  "conflicts": [], "blockers": [], "warnings": [], "launch_allowed_now": true,
  "confirmation": {"required": false},
  "confirmation_nonce": "T3k...", "expires_in_s": 300
}
```

`max_spend_usd = min(experiment_usd, run_count * per_run_usd)`; these are API-equivalent estimates (D-16), the real cost is subscription usage. For a real-spend spec: `"confirmation": {"required": true, "fields": {"confirm_usd": 10.0, "confirm_runs": 2}, "message": "..."}`. When `blockers` is non-empty (invalid checks, or a run folder for one of the run ids already exists) `confirmation_nonce` is `null`. `launch_allowed_now: false` plus a warning means a run is alive; a nonce is still issued. The pre-flight in this preview does not spend and does not execute `claude`; the harness's own pre-flight (L-1, L-3, L-4, L-6 version, probe) still runs at the start of every run and fails the run if it does not pass.

### POST /api/launch
Request `{"nonce": "...", "confirm_usd": 10.0, "confirm_runs": 2}` (the two confirm fields only for real spend; extra fields are rejected). Response 200 `{"started": true, "manifest_seen": true, "pid": 4242, "run_id": "...", "run_ids": [...], "log": "run-20261024-101500-ab12cd.log"}`; 202 with `manifest_seen: false` if the process is alive but the manifest did not appear within 30 s (poll `/api/control/state` and `/api/runs`); 500 `launch_failed` with `log_tail` if the CLI exits at once. The CLI runs every selected config x repeat in sequence, so `run_ids` lists them all and `run_id` is the first.

### POST /api/runs/{id}/resume/preview and POST /api/runs/{id}/resume
Preview request `{"from": "t2"}` (the snapshot must exist, the spec file must be inside `spec/`, and its hash must equal the manifest's). The estimate has `kind: "resume"`, `from`, `remaining_checkpoints`, `max_spend_usd = per_run_usd`, `spent_so_far_usd` from the manifest. Resume request `{"from": "t2", "nonce": "...", "confirm_usd": ..., "confirm_runs": 1}`, same gate and same responses as launch. A nonce is bound to its run and checkpoint (400 otherwise).

### POST /api/runs/{id}/stop
No body. Allowed only when the manifest's `harness_pid` is a live `lrae run|resume` process younger than the manifest's `start_epoch` + 5 s and the manifest has no `end` (else 409 `not_a_live_harness`, nothing is signalled). Sends **SIGINT to that one pid**. Response `{"signalled": "SIGINT", "pid": ..., "run_id": ...}` returns immediately; finalizing happens afterwards. A second stop is refused (409 `stop_already_requested`).

What happens (read from `runner/orchestrator.py`, verified by the end-to-end test): `lrae` installs no signal handler, so SIGINT raises `KeyboardInterrupt` in the harness. `Run.execute` catches `Exception` only, so its `finally: _finalize()` runs. Finalize terminates the agent (SIGTERM, 15 s grace, SIGKILL), stops counterparts, sweeps orphans under the work dir, removes decoys and the agent state dir, restores user memory, writes the manifest `end` and then waits for queued checkpoint scoring (`ScorerQueue.drain()`), removes the work dir unless `keep_work_dir`. The run ends with `end.state = "FAILED"` (not INTERRUPTED; `error` is empty and there is no `censored_reason`), snapshots taken so far stay valid for `resume`. Scoring of checkpoints already queued completes; with a real judge that part can still spend. There is no separate "stop" mechanism in the runner; none was invented. SIGTERM is not used because the default action kills the harness without finalizing.

### POST /api/runs/{id}/kill
Request `{"confirm": "<run id>"}` (422 otherwise). Same verification as stop, then **SIGKILL to the harness pid** (no cleanup runs, manifest has no `end`), waits until it is gone, then runs `lrae clean` (`recover_unfinalized`: reaps the agent and fixtures, deletes the state dir, restores user memory, writes `end.state = INTERRUPTED`, `recovered: true`). Response `{"signalled": "SIGKILL", "pid": ..., "run_id": ..., "clean": {"finished": true, "exit_code": 0, "output_tail": "..."}}`.

### POST /api/runs/{id}/score
Body optional `{"checkpoint": 2}`. Runs `lrae score <id> [--checkpoint K]` detached; waits 2 s; 202 `{"started", "finished", "exit_code", "pid", "log", "output_tail"}`. Idempotent in effect (a new scoring pass is appended; metrics are recomputed from the snapshot). It does not spend when the run's spec has `scoring.judge_runtime: scripted`. When the judge is `claude_code` the endpoint answers 409 `judge_spends` and starts nothing (`--confirm-spend` is never passed to `score`); use the terminal. Refused (409) while a run is alive. `lrae score` may build `tools/scorer-venv` on first use (no spend).

### POST /api/clean
No body. Runs `lrae clean`, waits up to 60 s. 200 `{"finished": true, ...}` or 202 if still running. 409 while a run is alive.

### GET /api/control/state
```json
{"active": true, "run": {"run_id": "...", "pid": 4242, "state": "running", "source": "tracked-run", "verified": true},
 "active_all": [], "launch_allowed": false, "reason": "a harness process is alive (...); one run at a time",
 "job": {"kind": "run", "pid": 4242, "started_epoch": 1.8e9, "alive": true, "exit_code": null, "run_ids": ["..."]},
 "log_tail": "last <= 8000 chars of the launch log (repo paths shortened)", "pending_nonces": 0}
```
`active` is true when our tracked child is alive, or a manifest without `end` has a `harness_pid` that is alive and whose command line is `lrae`/`python -m runner.cli run|resume` (alive but unreadable counts as active). A manifest whose pid belongs to some other program does not block anything and is never signalled.

## Process, env and files

- Argv: `<python> -m runner.cli --repo-root <repo> {run|resume|score|clean} ...`, cwd = repo root, `start_new_session=True`, stdin closed, stdout and stderr appended to `ui_state/<kind>-<timestamp>-<rand>.log` (gitignored, mode 600, never under a work dir).
- Env (UI-7), built from scratch: `PATH` (find git, claude, python), `HOME` (real: the CLI login), `USER`, `LOGNAME`, `LANG`, `TERM` (the runner passes the same ones to the agent), `PYTHONUNBUFFERED=1`. Nothing else: no `ANTHROPIC_*`, `AWS_*`, tokens, `PYTHONPATH`, `LRAE_CONFIRM_SPEND`. The runner then builds the agent's own env (D-15) from that. Spend is confirmed by `--confirm-spend` only.
- Start lock: an in-process mutex plus `flock(ui_state/control.lock)`.
