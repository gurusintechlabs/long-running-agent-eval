# Phase 1 Summary: Spec and local runner

**Branch:** `phase-1-spec-sandbox` · **Spec:** v0.4 · **Date:** 2026-10-16

## Exit check status

> *One run completes and snapshots reproducibly.*

| Part | Status |
|---|---|
| Scripted-runtime run completes and snapshots (4 checkpoints) | **Met.** `tests/integration/test_orchestrator.py::test_scripted_run_completes_with_all_artifacts` |
| Two scripted runs give identical snapshot tree hashes at every checkpoint | **Met.** `test_runs_are_reproducible` compares `worktree_hash` and `head_tree` for t1..t4 |
| Real Claude Code CLI smoke run | **Met, in a smaller form** the owner approved: 30 s, two checkpoints, `claude-haiku-5-5` (Opus 5.5 is not available on CLI 1.0.126, D-17). `tests/live/test_smoke_claude_code.py` passed. |
| Platform-limit soak test (≥ 3 h) | **Dropped by the owner** (cost). Written, never run: `tests/live/test_soak.py` |

The exit check is **met** for both the scripted runtime and the real CLI (with a cheaper model, pending D-17).

## What was built

| Area | Files |
|---|---|
| Spec schema, loader, `spec_hash`, run IDs | `spec/schema.py`, `spec/loader.py`, `spec/configs/A.yaml`, `spec/examples/pilot.yaml` |
| Clean memory (L-1, L-3, D-15) | `runner/memory.py`: state-dir path, empty-at-start check, snapshot/restore/delete, ancestor and seed checks, user-memory move-aside guard with crash recovery |
| Run folders, scrubbed env, seed clone, venv | `runner/workdir.py` |
| Process-group control | `runner/procs.py`: spawn in own session, SIGSTOP/SIGCONT, terminate with grace, orphan sweep (restricted to processes started after the run began) |
| Telemetry | `telemetry/events.py` (append-only JSONL, fsync, redaction), `telemetry/otlp_receiver.py` (stdlib, loopback only, http/json + gzip), `telemetry/counters.py` (cumulative cost only) |
| Snapshots + local mirror tags (D-5) | `runner/snapshot.py` |
| Pre-flight | `runner/preflight.py` (L-1, L-3, L-4, L-6, `init` inspection), `runner/probe.py` (one real turn: no MCP/plugins/skills, telemetry arrives) |
| Runtimes | `runner/runtimes/claude_code.py`, `scripted.py`, `scripted_agent.py` (stand-in `claude -p`) |
| Lifecycle | `runner/orchestrator.py`, `loop_driver.py`, `resume.py`, `manifest.py`, `prompt.py`, `cli.py` |
| Seed fixture + pilot task | `fixtures/seed_export_service/` (529 app lines, 17 tests, `vendor/`, lock file), `fixtures/build_seed.py` (SHA `07b476cee11f71c3364e0c39bdd7de5a80f86b10`), `fixtures/tasks/export_csv/{prompt.md,constraints.yaml}` |

CLI: `lrae validate | run | resume | clean`. `score`, `ingest`, `dashboard` and `report` exit with "not implemented" (later phases).

## What was tested

`pytest -m "not api"` (default plus `-m local`): **181 passed, 1 skipped** (the skip is a loopback-interface check that cannot run when this machine's hostname resolves to loopback), 2 live tests deselected (~2 min). One intermittent failure showed up during development (bug 6 below); it is fixed and was confirmed with 6 rounds under full CPU load.

Covered, with no API spend:
- Spec rejection cases (aliases, short SHA, dt not dividing duration, work_dir inside repo, script rules) and hash stability.
- Env scrub: no `GITHUB_TOKEN`/AWS/`ANTHROPIC_*` leak, checked both on the dict and from inside a running scripted agent (`env` dump).
- Clean memory: state dir empty at start, snapshotted, deleted in every terminal state and after a harness crash; user `CLAUDE.md` and `rules/` hidden during the run and restored byte-identically, including when pre-flight or the probe fails.
- Real-agent code path with a stub `claude`: exact flags, `--session-id` on the first turn then `--resume` with the same ID, version mismatch stops before any turn, no run without spend confirmation.
- Crash and resume: harness `SIGKILL`ed after t2, `lrae resume --from t2` finishes the run, no stray processes, no leftovers.
- Orphan sweep kills `setsid`-escaped processes; SIGSTOP freezes escaped children too.

Ruff is clean (`E,F,I,B`; fixtures excluded).

## Live verification (CLI 1.0.126, run 2026-10-16 with the owner's approval)

Cost: a handful of one-turn Haiku calls, one rejected Opus call (free), and one 63-second smoke run (about ten Haiku turns).
The soak test was **dropped by the owner** (cost); `tests/live/test_soak.py` stays in the repo, unrun.

| Question | Answer |
|---|---|
| Does the CLI export OTel in a format the receiver can read? | **Yes: `http/json`**, posted to `/v1/logs` and `/v1/metrics`. But the first attempt flattened 0 records: the CLI sends **chunked bodies with no `Content-Length`**. Receiver fixed (with tests). |
| Event names | The prefixed *body* is canonical (`claude_code.api_request`); `event.name` is the bare `api_request`. Values such as `cost_usd` and token counts are **strings**. Metrics: `claude_code.cost.usage`, `claude_code.token.usage` (`type`: input/output/cacheRead/cacheCreation). |
| Privacy | **Every record carries your email, account UUID, user ID and organization ID.** The receiver now redacts them before writing (raw and flattened); a test asserts none reach disk. Prompt text arrives as `<REDACTED>`. |
| Is `--model claude-opus-5-5` accepted? | **No, not by CLI 1.0.126.** The API answers 400 `claude_code_version_too_old`: version **2.1.280 or newer** is required. `claude-haiku-5-5` is accepted. The CLI's own default model (`claude-sonnet-4-20250514`) returns 404, which is why every turn passes `--model`. See D-17. |
| Does `--setting-sources project,local` keep a user `CLAUDE.md` out? | **No.** With a canary in `~/.claude/CLAUDE.md`, the agent repeated it with no flags (control), with `project,local`, and with `project` only. So the **move-aside guard is required**, not a fallback, and it is what the orchestrator uses. The live smoke test passed with it (canary never reached the agent; file restored; none existed originally). |
| User skills / plugins | `init` has no `plugins` or `skills` fields in this version; `slash_commands` and `agents` list only built-ins in every run, even with `~/.claude/skills` populated. The probe's check on those is vacuous for 1.0.126. |
| Does `memory.state_dir()` match the CLI's real path? | **Yes.** The smoke snapshots contain the CLI's session `.jsonl` files at the computed path, and no state dir remained afterwards. |
| Does the full orchestrator work against the real CLI? | **Yes** (haiku, 30 s, 2 checkpoints): probe passed, telemetry arrived, cost recorded from OTel (> $0), clean-memory checks held, no leftovers. |
| `claude -p` and stdin | An inherited open stdin makes `claude -p` hang waiting for end-of-input (my first probe timed out after 240 s). The harness always closes stdin. |
| Auth | `apiKeySource: none` in `init`: the subscription login is in use, as expected. |
| `--max-turns` | Not available in 1.0.126. |

Real captures, with account identifiers removed, are in `fixtures/otel/` and `fixtures/stream/` for the Phase 2 tests.

### Still unverified
- `--resume` against a *restored* state dir with the real CLI (resume is tested end to end only with the scripted agent).
- OTel events for tool use and API errors (`tool_result`, `tool_decision`, `api_error`): the smoke turns used no tools.
- Behaviour on a newer CLI (see D-17); everything above must be re-checked after updating, which `tests/live/test_smoke_claude_code.py` does cheaply.
- `auto_memory: off` (no mechanism found; raises `NotImplementedError`).
- Usage-limit behaviour and how long an Opus run lasts (needs real long runs; the Phase 4 dry run measures it).

### Bugs the live runs found (all fixed, with tests)
1. Receiver ignored chunked request bodies.
2. Cost counter would have summed 0 for real runs (assumed numeric values and a different event name), and crashed on a non-numeric value.
3. Pre-flight rejected the real tool list (`KillShell`, `SlashCommand` missing).
4. The seed fixture is plain files but the orchestrator tried to `git clone` it. Added `runner/seed.py` (deterministic build, cache, SHA verification).
5. My own early `ruff --fix` had rewritten 10 seed files and I had committed that, silently changing the pinned seed SHA. Caught by the new pinned-SHA test, restored from the verified commit, and fixtures are now excluded from linting.
6. **Intermittent run failure under load** (`PermissionError: Operation not permitted`, about 1 run in 4 when the machine was busy). macOS answers EPERM when you signal the process group of a process that has exited but not been reaped, and a checkpoint landing between two agent turns did exactly that. Now treated as "already gone" in all signalling paths; a deterministic test builds a zombie on purpose. Confirmed with 6 rounds of the previously failing tests under full CPU load (all pass). It surfaced only because I reran a failing test instead of dismissing it as flaky.

## Known limitations and deviations (for review)

- `budget.experiment_usd` is **not enforced yet.** It needs cost history, so it arrives with the guardrails (Phase 2) and the dry run (Phase 4). Per-run budgets (`per_run_usd`, `per_run_tokens`) are likewise Phase 2.
- On resume, `cumulative_cost` sums `otel.jsonl` across the crash; events the old process logged after the restored snapshot could be double-counted. Phase 2's counters should key cost by session and time window.
- The plan's `test_agent_env_live.py` (reading the agent's environment with `psutil`) is covered instead by the `env` dump check in `test_agent_env_is_scrubbed_during_run`.
- Configs B–E raise `NotImplementedError` (Phase 5).
- Scripted-run reproducibility relies on actions scheduled mid-interval (0.75 s margin at dt = 1.5 s). Heavily loaded machines could in principle break that; no flakiness seen in repeated full runs.
- The orphan sweep matches by working directory and (at the final sweep) open files. A process that `chdir`s out of the work dir and closes its files escapes it. This is part of the accepted local-mode gap (D-14).
- The seed lock includes `opentelemetry-api` (pulled in transitively by the pinned FastAPI). The Phase 3 `no_new_dependencies` probe must treat it as part of the seed set.
- The seed fixture's `.gitignore` is part of the pinned seed commit.

## Decisions to confirm

- **D-17 (open): the installed CLI cannot run `claude-opus-5-5`.** It needs Claude Code ≥ 2.1.280; this machine has 1.0.126. Options: (a) run `claude update` (changes your global CLI, which also affects your interactive use; I have not done it), then re-run the smoke test, which re-verifies flags, telemetry and the `CLAUDE.md` behaviour; (b) run studies on a model 1.0.126 accepts (e.g. `claude-haiku-5-5`), which is not what the pilot spec intends.
- D-2, D-3, D-5, D-12, D-14, D-15 and D-16 were implemented as written. D-15's mechanism 1 (flags) was **disproven**, so mechanism 3 (move-aside) is now the verified mechanism rather than a fallback.
