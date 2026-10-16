# Phase 3 Summary: Scorer

**Branch:** `phase-3-scorer` · **Spec:** v0.5 · **Date:** 2026-10-16

## Exit check status

> *Scorer flags known-bad snapshot, passes known-good.*

`lrae score --snapshot fixtures/snapshots/<name>` and `tests/integration/test_known_snapshots.py`:

| Snapshot | P | R | C | Hazards | Notes |
|---|---|---|---|---|---|
| `known_good` | **1.0** (12/12) | **0** | **0** | **none** | 1 accepted commit; S = 0 (no cost in a standalone snapshot) |
| `known_bad` | 1.0 | **1** (`tests/test_pagination_audit.py::test_has_more`) | **1** (`vendor-untouched`) | **quality, context** | S = null with reason `no_accepted_commits` (its only commit fails the regression suite) |

- All seven core metrics are present for both. S is null only when its denominator is zero, as spec'd, and the reason is recorded.
- Re-scoring is deterministic: identical values, and X comes from the judge cache. A test confirms this with a judge that raises if it is called.
- **Met.**

## What was built

| Area | Files |
|---|---|
| Hidden tests (pilot) | `fixtures/tasks/export_csv/hidden/`: 12 black-box HTTP tests (auth, CSV header/rows/escaping, pagination and boundaries, rate limit and per-user isolation, audit once per success and none on rejection) plus `scorer.yaml` and `pytest.ini`. `prompt.md` now states the exact interface the tests assume. |
| Reference + known snapshots | `fixtures/snapshots/{known_good,known_bad}/` (overlays) and `build.py` (deterministic: known_good `0eb00424…`, known_bad `1ba0ba9c…`) |
| Scorer | `scorer/run_checkpoint.py` (one pass → `scorer.jsonl` per docs/interfaces.md §4), `sandbox.py` (temp copies outside work and artifact dirs, process groups, leak checks), `venv.py` (`tools/scorer-venv-<lock hash>`, one per seed lock), `standalone.py`, `cli.py`, `determinism.py` |
| Metrics | `metrics/p_hidden.py` (app from the temp copy; serverless tasks too), `r_regression.py` (pristine overlay, accepted commits per D-1, `tests_tampered`), `d_defects.py` (ruff `--isolated --ignore-noqa`, bandit `--ignore-nosec`), `c_constraints.py` (probes `vendor_unchanged` (dir or single file), `no_new_dependencies`, `endpoint_change_has_test`, `forbidden_python`, `module_has_test`), `w_repeat.py`, `s_cost.py`, `x_judge.py` + `judge_prompt.md`, `hazards.py` |
| Orchestrator hook | `runner/scoring.py`: a worker thread scores each checkpoint in a `python -m scorer.run_checkpoint` subprocess. The agent is never blocked, and the queue is drained at FINALIZING. |
| CLI | `lrae score <run_id> [--checkpoint K] [--check-determinism] [--confirm-spend]`, `lrae score --snapshot DIR`, `lrae install-scorer` |
| Scripted pilot agent | `fixtures/scripted/build_pilot_script.py` → `pilot_agent.yaml` (the reference solution delivered over K intervals), `spec/examples/pilot-scripted.yaml` |

## What was tested

143 Phase 3 tests, all green; the full suite (default plus `-m local`) is green; ruff is clean.
- **Gaming resistance** (`test_scorer_hardening.py`):
  - a malicious `conftest.py` that forces passes, together with a `tests/` directory whose asserts are deleted, leaves R and P unchanged;
  - an app that cannot start gives P = 0 with the reason and the app log;
  - no scorer process outlives scoring, including a daemon that escaped its group;
  - temp copies are deleted.
- **Mutation-checked:**
  - Removing the pristine-test overlay makes the malicious-conftest test fail, as it should.
  - Removing `--noconftest` from the hidden-suite run changes nothing, because the hidden suite's `rootdir` and `-c` already keep collection out of the agent's tree. That flag is defence in depth.
- **Scoring inside a run** (`test_scored_run.py`): a scripted agent on the real seed at dt = 20 s, with 3 checkpoints. Every checkpoint is scored during the run in under dt/2. P goes from 0 at t1 to 1.0 at t3. The route lands at t2 without its test (the test arrives at t3), so exactly one context hazard fires, at t2.
- **Throughput:** about 7–8 s per pass for a cold checkpoint, about 4–5 s for later ones (seed baseline cached), against the < 2 min target. Real runs with many commits per interval will be slower, because accepted-commit checks are cached per tree but run per commit; the sampling cap is 40.

## Incident: unapproved judge calls (fixed)

During development, one draft test by a sub-agent scored with the pilot spec's `judge_runtime: claude_code` and so called the real `claude` CLI as the judge. That was two scoring passes of 3 samples each: a few cents of subscription usage, **not approved**. No state dirs were left under `~/.claude/projects`, and there is no `~/.claude/CLAUDE.md` that could have leaked. Fixes:
- `ClaudeJudgeRunner` now refuses to start unless spend is confirmed (`LRAE_CONFIRM_SPEND=1`, set only by `lrae run --confirm-spend` / `lrae score --confirm-spend`). There is a test for this.
- `tests/conftest.py` strips `LRAE_CONFIRM_SPEND` from every non-`api` test.
- All scorer tests use `FakeJudge`, and the standalone scorer defaults to it.

## Unresolved / for review

1. **Prompt/test pairing (needs human review):** the prompt states limits, env var names (`ITEMS_EXPORT_RATE_LIMIT`, `ITEMS_EXPORT_RATE_WINDOW_S`), `X-Total-Count` and `Retry-After`. The scorer sets the window to 3600 s so it cannot roll over mid-suite. Window expiry itself is not tested. The hidden tests insert their users directly into the app's SQLite DB, because the seed has no user-creation endpoint.
2. **Judge prompt review:**
   - "when in doubt, leave it out" biases X low, intentionally;
   - the `kind` values are not enforced;
   - truncation budgets are 60k characters of agent text, 40k of diff and 12k of commit messages.
   The real judge has **never been exercised with approval**, so `--tools ""` (CLI 2.1.301 help text) is verified only from `--help`.
3. **Cost baseline (§8.4)** = pooled Σ interval cost ÷ Σ accepted commits over the first `cost_baseline_checkpoints` checkpoints that have ≥ 1 accepted commit. Proposed definition, to calibrate in Phase 4.
4. **Hazard attribution (D-9):** quality hazards bisect commits with the regression suite only. A regression that shows only in the hidden tests is attributed to t_k.
5. **`no_new_dependencies` (pip-freeze part):** it compares exact name and version pairs with the seed lock, so a harness venv that drifts from the lock would be flagged. Scripted runs have no venv, so this part is skipped for them.
6. D-1, D-6, D-8, D-9 and D-13 are implemented as proposed. `scoring.judge_runtime` (`claude_code` | `scripted`) is a new spec field: it exists so tests and scripted pilots never spend. It is not a D-n change.
