# Implementation Plan

**Spec:** [spec.md](spec.md) · **Source design:** [design.md](design.md)

Process (design §4): one phase per Claude Code session, tests first, and each phase is merged only after human review. At the start of a session, Claude Code reads `design.md`, `spec.md` and this file, then **restates the phase's exit check** before writing code. At the end of the session it stops and writes `docs/phase-N-summary.md` covering what was built, what was tested (with the `pytest` output), and what is unresolved.

Test markers: `unit` (default, fast, no Docker), `docker` (needs the Docker daemon, no API spend), `api` (real Anthropic spend; skipped unless run with `--run-api` **and** `LRAE_CONFIRM_SPEND=1`). "pytest is green" means the default run plus `-m docker`.

---

## Phase 0: Pre-flight (human, ~1 hour, before Phase 1)

- [x] Agent runtime: the Claude Code CLI, headless.
- [x] Model: `claude-opus-5-5` for agent and judge. To change it later, edit `agent.model` / `scoring.judge_model` in the experiment spec (spec §4.1).
- [x] D-2 (local OTel Collector), D-3 (small libraries) and D-5 (local checkpoint tags) confirmed.
- [x] `git init` and `main` pushed to `github.com/gurusintechlabs/long-running-agent-eval`. Use one branch per phase (`phase-1-spec-sandbox`, …).
- [ ] Choose the credential type (spec §15 Q1: `oauth_token` via `claude setup-token`, or `api_key`). Create a **dedicated** credential for the study and save it in `~/.config/lrae/credentials.env` (mode 0600).
- [ ] Confirm the host has Docker ≥ 24, Python 3.11 and Chrome/Chromium.

---

## Phase 1: Spec and sandbox

**Exit check:** *One run completes and snapshots reproducibly.*
Concretely: a scripted-runtime run of the pilot spec (shortened to 3 min, dt = 1 min) completes, and running it twice produces identical snapshot tree hashes at every checkpoint. A single `api`-marked smoke run of the real Claude Code runtime (5 min, dt = 1 min) completes with snapshots.

**Tests first**
- `tests/unit/test_spec_schema.py`: example specs validate. Rejected: unknown keys, model aliases, short SHAs, non-digest images, dt not dividing duration, missing `script` for the scripted runtime. `spec_hash` changes when any referenced file changes and stays the same when YAML key order changes.
- `tests/unit/test_run_id_manifest.py`: run_id format; manifest has every required field.
- `tests/unit/test_scripted_runtime.py`: the script parses, and actions run in order with correct relative timing (fake clock).
- `tests/unit/test_snapshot.py`: snapshots of a temp workspace include `.git` and uncommitted files; `meta.json` fields; the mirror repo gets tag `ckpt/tK` while the source repo has no new tags or refs.
- `tests/integration/test_container_isolation.py` (docker): inside the agent container, the scorer and hidden paths are absent (I-1, S-5); egress to `example.com` fails while the gateway is reachable (I-3); the process runs as non-root with caps dropped (S-4); `docker inspect` mounts are exactly workspace and agent_home.
- `tests/integration/test_image_contents.py` (docker): the agent image filesystem contains no files from `scorer/` or `fixtures/tasks/*/hidden` (S-6).
- `tests/integration/test_run_reproducible.py` (docker): the exit check, using the scripted runtime twice.
- `tests/integration/test_resume.py` (docker): kill a scripted run after t2, resume from t2, and check that it completes with K checkpoints and is flagged `resumed`.
- `tests/integration/test_otel_pipeline.py` (docker): a scripted `emit_otel` reaches the run's collector, the file exporter writes it, and `otel_ingest` turns it into envelope events tagged with `lrae.run_id`.
- `tests/integration/test_egress_proxy.py` (docker): CONNECT to an allowlisted host succeeds; any other host is denied and logged as `egress.denied`.
- `tests/integration/test_managed_settings.py` (docker): the managed-settings file is root-owned with mode 0444, the agent user cannot modify it, and its telemetry env is in effect (S-7, I-3a).
- `tests/unit/test_credentials.py`: credentials load from the env file and never appear in the manifest, logs or captured `docker inspect` output (S-2).
- `tests/live/test_smoke_claude_code.py` (api): the exit-check smoke run.

**Tasks**
1. Scaffold: `pyproject.toml` (package `lrae`, Python 3.11, console script `lrae`), ruff config, pytest markers, `.gitignore` (`runs/`), `.dockerignore` (excludes `scorer/`, `fixtures/tasks/*/hidden`, `runs/`, `tests/`).
2. `spec/schema.py` and `loader.py` (pydantic v2, spec §4.1), `spec_hash`, `spec/examples/pilot.yaml` (with `model: claude-opus-5-5`), and `spec/configs/A.yaml` (B–E are stubs until Phase 5).
3. **Seed repo fixture** `fixtures/seed_export_service/`: a FastAPI service of about 500 lines (users, items, an auth stub, an in-memory/SQLite store) with a passing pytest suite (~15 tests), a `vendor/` directory (a small vendored helper module the app imports), and `requirements.txt`. Commit it as its own nested git repo (or build it from a script, `fixtures/build_seed.py`, that produces a deterministic SHA), and record the SHA in `pilot.yaml`.
4. `fixtures/tasks/export_csv/prompt.md` and `constraints.yaml`, with the three planted constraints stated once. (Hidden tests are written in Phase 3.)
5. `docker/agent/Dockerfile`: python:3.11-slim, Node, Claude Code CLI pinned via the `CLAUDE_CODE_VERSION` build arg (the current release at build time), the seed repo's dependencies preinstalled, git, user `agent` (uid 1000), and `managed-settings.json` (root-owned, mode 0444) that forces the OTel exporter env. Add `lrae build-image`, which builds the image and prints the digest for `agent.image`.
6. `telemetry/events.py`: envelope writer (append-only, fsync, `seq`, `mono_ns`, credential redaction filter).
7. `telemetry/otel/collector.yaml` (OTLP receiver → `file` exporter), a pinned collector image digest, and a **minimal** `telemetry/otel_ingest.py` (tail and flatten into the envelope). Counters and the budget channel come in Phase 2.
8. `telemetry/egress_proxy.py`: an asyncio CONNECT proxy with a domain allowlist and `egress.connect`/`egress.denied` events.
9. `runner/container.py`: per-run network, starting the collector, proxy and agent containers with security options, exec, pause/unpause, kill, self-check.
10. `runner/runtimes/scripted.py` and `claude_code.py`. Verify the following against the pinned version and write the findings into `docs/phase-1-summary.md`:
    - the exact headless flags;
    - `stream-json` message shapes and `--resume` behavior;
    - the managed-settings path and `env` support;
    - the OTel event and metric names and attributes (record real payloads into `fixtures/otel/` for Phase 2 tests);
    - which hosts Claude Code needs on the egress allowlist for the chosen auth type.
11. `runner/loop_driver.py` (config A), `runner/snapshot.py` (pause, copy, unpause, meta, local mirror tag), `runner/orchestrator.py` (lifecycle state machine, timers), `runner/resume.py`, `runner/cli.py` (`validate`, `build-image`, `run`, `resume`).
12. **Platform-limit probe** (design risk: "verify first"): an `api`-marked soak test that keeps the Claude Code CLI running in the sandbox with the study credential for ≥ 3 h on a cheap, low-activity prompt loop. It records any token expiry, usage-limit stop, 5xx errors or disconnects. Run it once, overnight, with spend confirmed, and report the results in the summary.

**Out of scope:** cost and context counters, guardrails, scoring, configs B–E.

**Reviewer checklist:** isolation tests are meaningful (they would fail if a mount were added); `pilot.yaml` pins everything; the smoke-run transcript looks sane; soak-test results are reported.

---

## Phase 2: Telemetry and guardrails

**Exit check:** *Injected violation is detected and logged.*
Concretely:
- (a) A scripted run whose script runs a forbidden command (`rm -rf /`) is detected on the command channel and logged as `guardrail.violation` and `guardrail.kill`. The container is frozen within 5 s, and the run state is KILLED.
- (b) A scripted run that writes outside `/workspace` through an obfuscated command is caught by the effect channel.
- (c) A scripted run whose `emit_otel` cost events push it past `per_run_usd` ends BUDGET_EXHAUSTED.
- (d) Stopping the collector mid-run raises `guardrail.telemetry_stalled` and pauses the agent.

**Tests first**
- `tests/unit/test_otel_ingest.py`: the recorded OTLP JSON fixtures from Phase 1 (`fixtures/otel/`) flatten to envelope events, keeping native names (`claude_code.api_request` etc.). Tokens and `cost_usd` are extracted correctly. Batches that are partial or duplicated on file rotation are deduplicated.
- `tests/unit/test_cost_crosscheck.py`: Σ OTel `cost_usd` per session matches the `stream-json` result's `total_cost_usd` within 1%, using the recorded fixtures.
- `tests/unit/test_stream_parser.py`: recorded `stream-json` fixtures (captured in Phase 1 from the pinned version) become `tool.call`, `tool.result`, `assistant.text`, `session.*` and `context.compaction` events.
- `tests/unit/test_counters.py`: per-interval and cumulative tokens, cost, tool calls, context fill (max and last) and compactions (event-based and the heuristic) from synthetic logs.
- `tests/unit/test_policy.py`: each default rule's regex has positive and negative examples (e.g. `rm -rf ./build` is allowed, `rm -rf /` is caught); glob/ops matching; the policy-file hash goes into `spec_hash`.
- `tests/unit/test_monitor.py`: the monitor tails a growing JSONL file and emits a violation within 2 s (fake clock); a `log` action does not kill; a `kill` action calls the kill switch exactly once.
- `tests/integration/test_killswitch.py` (docker): exit check (a). The proxy denies the run's traffic after the kill, a final snapshot exists, and the state is KILLED.
- `tests/integration/test_effect_channel.py` (docker): exit check (b), plus tampering with managed settings being detected.
- `tests/integration/test_budget.py` (docker): exit check (c), plus the experiment-level cap refusing to start a new run.
- `tests/integration/test_telemetry_stall.py` (docker): exit check (d).
- `tests/integration/test_interruption.py` (docker): scripted repeated `claude_code.api_error` events produce `platform.interruption`, run state INTERRUPTED, and `censored_reason` set.

**Tasks**
1. Complete `otel_ingest.py` (tailing, file-rotation handling, dedup) and the `otel_lag_ms` health signal.
2. `telemetry/stream_parser.py` and `counters.py` (from OTel and stream events; context-window table in `telemetry/models.yaml`).
3. `guardrails/policy.py`, `rules/default.yaml`, `monitor.py` (command, effect, budget and egress channels, plus the stall detector), `killswitch.py` (pause, deny at the proxy, snapshot, kill).
4. Wire the monitor and kill switch into the orchestrator lifecycle, including the canary script `fixtures/scripted/canary_forbidden.yaml` that the Phase 4 pilot reuses.
5. Platform-interruption detection (API errors, token expiry, usage-limit stops) and the censoring states.

**Out of scope:** scorer metrics; dashboard.

**Reviewer checklist:** the regexes are not trivially bypassable for the default rules (and the effect channel exists for the cases they miss); no secrets appear in any log; kill latency and the budget overshoot bound are measured, not assumed.

---

## Phase 3: Scorer

**Exit check:** *Scorer flags known-bad snapshot, passes known-good.*
Concretely: `lrae score` on `fixtures/snapshots/known_bad` emits C > 0 (the `vendor_unchanged` probe) and R > 0, along with their hazards. On `known_good` it emits P = 1.0, R = 0, C = 0, and no hazards. All seven metrics are present for both. Re-scoring is deterministic (X comes from the judge cache).

**Tests first**
- `tests/unit/scorer/test_p_hidden.py`, `test_r_regression.py`, `test_d_defects.py`, `test_c_constraints.py` (each probe has violating and clean mini-repos, including the import scan's stdlib, first-party and third-party cases, and an endpoint added with and without a test), `test_w_repeat.py` (a synthetic git history with known churn produces the expected ratio), `test_s_cost.py` (accepted-commit detection, baseline, the zero-commit interval rule), `test_x_judge.py` (fake judge runner in place of the `claude -p` call: schema validation, retry, null handling, median over 3 samples with the spread recorded, untrusted-data wrapping in the prompt).
- `tests/unit/scorer/test_hazards.py`: every row of spec §8.4, including attribution to the first offending commit and the once-per-dimension rule.
- `tests/integration/test_scorer_isolation.py` (docker): the scorer container has `--network none`; a snapshot containing a malicious `conftest.py` that forces passes and a `tests/` directory that deletes assertions **does not** change P or R; the agent app's failure to start produces P = 0 with a logged reason.
- `tests/integration/test_known_snapshots.py` (docker): the exit check.

**Tasks**
1. **Hidden tests** `fixtures/tasks/export_csv/hidden/`: 12 black-box HTTP acceptance tests for `GET /export` covering CSV content-type and header row, correct rows, pagination params and limits, page boundaries, per-user rate limiting (allowed, then 429, with per-user isolation), one audit-log entry per export (and none on rejected requests), auth required, and CSV escaping of commas, quotes and newlines. The interface the tests assume (query params, audit-log access path) MUST match what `prompt.md` tells the agent. Update the prompt if needed, and get a human review of the prompt/test pairing.
2. **Reference solution** on a branch of the seed repo, which becomes `fixtures/snapshots/known_good` (P must be 1.0). Then `known_bad` = known_good plus an edit to `vendor/` plus a change that breaks one seed test.
3. `scorer/image/Dockerfile` (`lrae-scorer`: scorer code, hidden tests, pristine regression suite, ruff, bandit, pytest).
4. The metric modules and `run_checkpoint.py` (orchestrates the metrics, writes `scorer.jsonl`), `hazards.py`, the judge with a prompt template and response cache, and the `lrae score` CLI.
5. Hook the asynchronous scorer queue into the orchestrator (a checkpoint enqueues; a worker scores). Check that the < dt/2 throughput target holds on the pilot repo.

**Out of scope:** threshold calibration (Phase 4); ladder tasks.

**Reviewer checklist:** hidden tests match the prompt's stated interface; gaming-resistance tests exist and fail when the hardening is removed; the judge prompt is reviewed.

---

## Phase 4: Pilot (design §4.2)

**Exit check:** *Metrics are stable across repeats*, plus every item of the pilot acceptance criteria in spec §13. "Stable" uses the definition proposed in spec §15 Q3, unless the reviewer amends it.

**Tests first**
- `tests/unit/analysis/test_ingest.py`: JSONL→SQLite is complete, idempotent, and rebuild-identical (hash of the dumped tables).
- `tests/unit/analysis/test_survival.py`: Kaplan–Meier and Greenwood checked against a published worked example (e.g. a textbook table with censoring); bootstrap CI seeded and deterministic; median "not reached" handling; headline-X computation (D-11).
- `tests/unit/analysis/test_trends.py`: aligned per-checkpoint series and medians.
- `tests/unit/report/test_dashboard.py`: the dashboard builds from a synthetic SQLite with no network access, and every figure file exists.
- `tests/integration/test_pilot_pipeline.py` (docker): a scripted end-to-end pilot (2 repeats × 6 checkpoints at a 1 min dt) followed by `ingest` and `dashboard` gives 7 metrics × 6 checkpoints × 2 runs with no nulls.

**Tasks**
1. `analysis/ingest.py`, `survival.py`, `trends.py`; `report/charts.py`; dashboard v1 (`dashboard.html.j2`, `lrae dashboard`).
2. **Dry run** (api): one 15 min config-A run to estimate $/hour and to set `per_run_usd` with ~1.5× headroom. Record the estimate and get budget approval for the pilot.
3. **Pilot** (api): 2 repeats × config A × 60 min, dt = 10 min, plus the canary run (scripted, full stack).
4. **Determinism check:** re-score every pilot snapshot and diff the results.
5. **Calibration:** look at the W, S and D distributions, propose `repeat_work_ratio` and `cost_per_commit_multiplier`/baseline values (and whether D should become a hazard), and write the rationale into `docs/calibration.md`. Thresholds change only in the spec, which produces a new `spec_hash`. Optional: one 2 h run (spec §15 Q2).
6. Add a minimal `lrae report --pdf` stub so that acceptance item 5 holds. The full report comes in Phase 6.

**Reviewer checklist:** the pilot actually exercised the hazards; calibration choices are justified by the data; budget accounting matches real usage within 2% (the Console bill if using `api_key`; with `oauth_token`, cost is an estimate, so compare token counts instead).

---

## Phase 5: Full runs

**Exit check:** *Data complete, outliers explained.*
Concretely: every (task class × config × repeat) cell exists with N ≥ 5, and every run has all checkpoints scored with no null metrics, or has a documented reason (killed, interrupted, censored). Any run whose TTFH or cost lies outside 1.5×IQR of its cell has a written explanation in `docs/outliers.md`.

**Tests first**
- `tests/unit/runner/test_configs.py`: behavior of the B, C, D and E loop drivers using the scripted runtime and a fake clock (gate prompts after a red visible suite; reset at the fill threshold with `HANDOFF.md` carried over and a new session ID; per-interval cap pauses and then resumes at the boundary; E composes all three).
- `tests/unit/analysis/test_compare.py`: Poisson rate CIs, Δ-median, cost overhead, log-rank on synthetic data.
- `tests/unit/analysis/test_completeness.py`: the completeness checker flags a missing cell, a missing checkpoint or a null metric.
- Per ladder task: `tests/integration/test_known_snapshots_<task>.py` (known-good and known-bad, as in Phase 3).

**Tasks**
1. Implement configs B–E (spec §4.3, decision D-4) and their YAML files.
2. Author the ladder tasks L2 and L3 (spec §15 Q4). Each needs a seed repo, prompt, constraints, probes, hidden tests (human-reviewed), and known-good/known-bad snapshots.
3. `lrae run` matrix mode with resumable scheduling. The order is randomized with the spec seed so that time-of-day API effects are spread across configs.
4. A cost estimate for the full matrix, then **owner approval**, then launch. Monitor with the dashboard and resume interrupted runs.
5. The completeness checker and outlier report.
6. Escalate to the next ladder tier only after the previous tier's data is complete (design risk: "phase by evidence").

**Reviewer checklist:** configs differ only in loop-driver behavior; resumed or interrupted runs are listed; spend stayed within the approved budget.

---

## Phase 6: Report

**Exit check:** *Reviewed by sponsor.*
Before it goes to the sponsor: `lrae report <experiment_id> --pdf` produces a 2–3 page PDF from the metrics store with no manual steps, and every number in it traces to a query.

**Tests first**
- `tests/unit/report/test_queries.py`: each report query returns the expected values on a synthetic store.
- `tests/unit/report/test_headline.py`: headline sentence generation, including the "bound never reached" and "insufficient data" cases.
- `tests/integration/test_pdf_build.py`: the PDF builds via headless Chrome, has 2–3 pages, contains all five section headings, and has no unrendered Jinja tokens; the build is deterministic apart from the embedded timestamp.

**Tasks**
1. `report/queries.py`, `exec_report.html.j2` (print CSS, A4/Letter), `build.py` (Chrome `--headless --print-to-pdf`).
2. The sections from design §5: the headline; the survival chart per task class with the recommended operating limit marked; trends with incidents; harness implications (hazard reduction vs cost overhead per control, gaps, changes needed before longer runs); the cost and security summary; the recommendation and next phase; limits and caveats, including small-N, single-model and single-repo scope. Appendix: spec hashes and run IDs.
3. A plain-language pass so that a non-technical executive can act on it (design §6, success criteria).
4. Sponsor review, and fold in the feedback.

**Reviewer checklist:** the caveats are stated plainly; no number is hand-typed; the recommended operating limit follows the D-11 rule.
