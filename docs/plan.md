# Implementation Plan

**Spec:** [spec.md](spec.md) (v0.4, local mode, installed CLI, clean memory) · **Source design:** [design.md](design.md)

Process (design §4): one phase per Claude Code session, tests first, and each phase is merged only after human review. At the start of a session, Claude Code reads `design.md`, `spec.md` and this file, then **restates the phase's exit check** before writing code. At the end of the session it stops and writes `docs/phase-N-summary.md` covering what was built, what was tested (with the `pytest` output), and what is unresolved.

Test markers:
- `unit`: the default; fast, with no subprocess agents.
- `local`: spawns real local processes (scripted runtime, receiver, scorer); no API spend.
- `api`: real Anthropic spend. Skipped unless run with `--run-api` **and** `LRAE_CONFIRM_SPEND=1`.

"pytest is green" means the default run plus `-m local`. Docker is not required for Phases 1–6.

---

## Phase 0: Pre-flight (human, before Phase 1)

- [x] Agent runtime: the Claude Code CLI, headless.
- [x] Model: `claude-opus-5-5` for agent and judge. To change it later, edit `agent.model` / `scoring.judge_model` in the experiment spec (spec §4.1).
- [x] D-2 (local OTel), D-3 (small libraries), D-5 (local checkpoint tags), D-12 (existing CLI login), D-14 (local mode is good enough for the report) and D-15 (clean memory per workspace) confirmed.
- [x] Repo on `github.com/gurusintechlabs/long-running-agent-eval`, `main`. Use one branch per phase (`phase-1-spec-sandbox`, …).
- [x] The Claude Code CLI is installed and logged in on this machine.
- [ ] Confirm the host has Python 3.11, git and Chrome/Chromium.
- [ ] Confirm that `~/lrae-work` (or another `work_dir`) has no `CLAUDE.md`/`.claude/` in its ancestors. Check `~` itself in particular.
- [ ] Accepted risk: the agent runs as your user with your login and `--dangerously-skip-permissions`.

---

## Phase 1: Spec and local runner

**Exit check:** *One run completes and snapshots reproducibly.*
Concretely:
- A scripted-runtime run of the pilot spec (shortened to 3 min, dt = 1 min) completes, and running it twice produces identical snapshot tree hashes at every checkpoint.
- A single `api`-marked smoke run of the real Claude Code CLI (5 min, dt = 1 min) passes pre-flight, completes with snapshots, and leaves OTel events in `events/otel.jsonl`.

**Tests first**
- `tests/unit/test_spec_schema.py`:
  - Example specs validate.
  - Rejected: unknown keys, model aliases, short SHAs, dt not dividing the duration, `work_dir` inside the repo, a missing `script` for the scripted runtime.
  - `spec_hash` changes when any referenced file changes and stays the same when YAML key order changes.
- `tests/unit/test_run_id_manifest.py`: run_id format; the manifest has every required field and no credential.
- `tests/unit/test_env_scrub.py`: the agent env contains only allowlisted keys (L-2), and host variables such as `GITHUB_TOKEN`, `AWS_*`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` and `SSH_AUTH_SOCK` are dropped. `HOME` is the real home; `TMPDIR` points into the work dir.
- `tests/unit/test_memory.py` (L-3, D-15):
  - The agent-state-dir path is computed correctly for a workspace path; the encoding is verified against the installed CLI in Phase 1.
  - Pre-flight fails if the state dir is non-empty at start, or if the seed contains `CLAUDE.md`/`.claude/`.
  - The state dir is copied into each snapshot and deleted at finalize, for **every** terminal state (COMPLETED, KILLED, BUDGET_EXHAUSTED, INTERRUPTED, FAILED) and after a simulated harness crash followed by restart.
  - The user-memory exclusion picks the first working mechanism. If the move-aside fallback is used, `~/.claude/CLAUDE.md` is restored byte-identical in every terminal state and after a crash (tested against a temp `HOME`, never the real one).
  - Two runs never share a folder or a state dir.
  - `lrae clean` removes leftovers only for `work_dir` paths and never touches other projects.
- `tests/unit/test_preflight.py`: a `CLAUDE.md` in an ancestor of the workspace fails the check (L-1); a harness path or a symlink into the repo inside the work dir fails it (L-4, S-5).
- `tests/unit/test_scripted_runtime.py`: the script parses, and actions run in order with correct relative timing (fake clock).
- `tests/unit/test_snapshot.py`: snapshots include `.git` and uncommitted files, exclude `venv/`, and record `pip freeze`. The mirror repo gets tag `ckpt/tK` while the agent's repo has no new tags or refs.
- `tests/unit/test_otlp_receiver.py`: POSTs to `/v1/logs` and `/v1/metrics` (http/json) are written to raw and envelope files; the receiver binds to loopback only; malformed bodies are logged, not crashed on.
- `tests/integration/test_procs.py` (local): SIGSTOP and SIGCONT freeze and resume a process group (a ticking child stops ticking). The orphan sweep kills a `setsid`/`nohup`-backgrounded child whose cwd is in the work dir (S-6).
- `tests/integration/test_run_reproducible.py` (local): the exit check, using the scripted runtime twice.
- `tests/integration/test_resume.py` (local): kill a scripted run after t2, resume from t2, and check that it completes with K checkpoints and is flagged `resumed`.
- `tests/integration/test_agent_env_live.py` (local): during a scripted run, `psutil.Process(pid).environ()` of the agent subprocess matches the allowlist (S-4).
- `tests/live/test_smoke_claude_code.py` (api): the exit-check smoke run, plus these clean-memory checks:
  - No MCP servers or plugins appear in `init`.
  - **Memory canary:** with a temporary canary line added to `~/.claude/CLAUDE.md` (backed up and restored by the test), the agent's probe reply MUST NOT reveal it. The test also checks that no state dir for the run remains afterwards (S-3).

**Tasks**
1. Scaffold: `pyproject.toml` (package `lrae`, Python 3.11, console script `lrae`), ruff config, pytest markers, `.gitignore` (`runs/`, `tools/`).
2. `spec/schema.py` and `loader.py` (pydantic v2, spec §4.1), `spec_hash`, `spec/examples/pilot.yaml` (`model: claude-opus-5-5`, `isolation.mode: local`, and `claude_code_version` set to the current `claude --version`), and `spec/configs/A.yaml` (B–E are stubs until Phase 5).
3. `runner/memory.py`: compute the agent state dir, run the start-empty check, snapshot it, delete it, and `lrae clean`.
4. **Seed repo fixture** `fixtures/seed_export_service/`: a FastAPI service of about 500 lines (users, items, an auth stub, a SQLite store) with a passing pytest suite (~15 tests), a `vendor/` directory (a small vendored helper module the app imports), `requirements.txt`, and a pinned `requirements.lock`. Build it deterministically with `fixtures/build_seed.py` so the SHA is stable, and record the SHA in `pilot.yaml`.
5. `fixtures/tasks/export_csv/prompt.md` and `constraints.yaml`, with the three planted constraints stated once. (Hidden tests are written in Phase 3.)
6. `telemetry/events.py`: envelope writer (append-only, fsync, `seq`, `mono_ns`, redaction filter).
7. `telemetry/otlp_receiver.py`: a stdlib `ThreadingHTTPServer` on `127.0.0.1:<free port>` that writes raw and envelope JSONL. Counters and the budget channel come in Phase 2.
8. `runner/workdir.py` (work dir layout, seed clone, per-run venv with a wheel cache, env scrub, harness settings file), `runner/procs.py` (spawn in a new session, SIGSTOP/SIGCONT/SIGTERM/SIGKILL on the group, `psutil` descendant tracking, orphan sweep), `runner/preflight.py`.
9. `runner/runtimes/scripted.py` and `claude_code.py`. Verify the following against the pinned version and write the findings into `docs/phase-1-summary.md`:
    - the exact headless flags, including `--settings` precedence over project settings;
    - the `stream-json` message shapes, the `init` contents, and `--resume` behavior after the state dir is restored;
    - **clean memory (D-15):** which mechanism keeps `~/.claude/CLAUDE.md` and user settings (hooks, plugins) out (`--setting-sources`, or something else); whether `--strict-mcp-config` with an empty config drops every MCP server; how to turn auto-memory off (for `auto_memory: off`) and where it is stored; how the CLI encodes workspace paths under `~/.claude/projects/`;
    - the OTLP protocols supported (http/json?), plus the OTel event and metric names (record real payloads into `fixtures/otel/` and `fixtures/stream/` for Phase 2 tests);
    - whether `permissions.deny` and built-in Bash sandboxing are available under `--dangerously-skip-permissions` (spec §3.2 optional hardening).
10. `runner/loop_driver.py` (config A), `runner/snapshot.py`, `runner/orchestrator.py` (lifecycle state machine, timers, `caffeinate` on macOS), `runner/resume.py`, `runner/cli.py` (`validate`, `run`, `resume`, `clean`).
11. **Platform-limit probe** (design risk: "verify first"): an `api`-marked soak test that keeps the CLI running on your existing login for ≥ 3 h on a cheap, low-activity prompt loop. It records any login expiry, usage-limit stop, 5xx errors, disconnects or sleep gaps. Run it once, with spend confirmed, and report the results in the summary.

**Out of scope:** counters, guardrails, scoring, configs B–E, Docker.

**Reviewer checklist:**
- The env-scrub and pre-flight tests would fail if a variable or path leaked.
- The smoke run's `init` message shows no personal MCP servers, plugins or `CLAUDE.md` content, and the memory canary passed.
- `~/.claude/projects/` has no leftovers from test runs.
- `pilot.yaml` pins everything.
- The soak-test results are reported.

---

## Phase 2: Telemetry and guardrails

**Exit check:** *Injected violation is detected and logged.*
Concretely, every case runs with the scripted runtime on the real harness:
- (a) A forbidden command (`rm -rf /`) is detected on the command channel and logged as `guardrail.violation` and `guardrail.kill`. The process group is frozen within 2 s, and the state is KILLED.
- (b) A `cat` of a file in this repo's `fixtures/tasks/*/hidden` is detected as `harness-access` and the run is killed.
- (c) A write to `.claude/settings.json` in the workspace, made through an obfuscated command, is caught by the effect channel.
- (d) `emit_otel` cost events past `per_run_usd` end the run BUDGET_EXHAUSTED.
- (e) Stopping the receiver mid-run raises `guardrail.telemetry_stalled` and pauses the agent.

**Tests first**
- `tests/unit/test_otel_ingest.py`: the recorded OTLP fixtures from Phase 1 flatten to envelope events, keeping native names. Tokens and `cost_usd` are extracted correctly, and duplicate batches are deduplicated.
- `tests/unit/test_cost_crosscheck.py`: Σ OTel `cost_usd` per session matches `stream-json` `total_cost_usd` within 1%, using the recorded fixtures.
- `tests/unit/test_stream_parser.py`: recorded `stream-json` fixtures become `tool.call`, `tool.result`, `assistant.text`, `session.*` and `context.compaction` events.
- `tests/unit/test_counters.py`: per-interval and cumulative tokens, cost, tool calls, context fill (max and last) and compactions (event-based and the heuristic).
- `tests/unit/test_policy.py`: each default rule has positive and negative examples (e.g. `rm -rf ./build` is allowed, `rm -rf /` is caught). Path resolution covers `..`, `~`, symlinks and quoted paths for `out_of_workspace`. The `{WORK}`/`{REPO}` substitution works, and the policy hash goes into `spec_hash`.
- `tests/unit/test_monitor.py`: the monitor tails a growing JSONL file and emits a violation within 2 s (fake clock). A `log` action does not kill; a `kill` action calls the kill switch exactly once.
- `tests/integration/test_guardrail_cases.py` (local): exit checks (a)–(e), each with a final snapshot present where applicable.
- `tests/integration/test_interruption.py` (local): scripted repeated `claude_code.api_error` events produce `platform.interruption` and INTERRUPTED with `censored_reason` set. A simulated clock gap (sleep) is detected.

**Tasks**
1. Complete OTel ingest (dedup, `otel_lag_ms`); add an `http/protobuf` parser only if Phase 1 found it necessary.
2. `telemetry/stream_parser.py`, `counters.py` and `models.yaml`.
3. `guardrails/policy.py`, `rules/default.yaml`, `monitor.py` (command, effect and budget channels, plus the stall detector), `killswitch.py` (SIGSTOP, snapshot, SIGKILL, orphan sweep).
4. Wire them into the orchestrator lifecycle. Add the canary scripts `fixtures/scripted/canary_forbidden.yaml` and `canary_harness_read.yaml`, which the Phase 4 pilot reuses.
5. Platform-interruption detection and the censoring states.

**Out of scope:** scorer metrics; dashboard.

**Reviewer checklist:**
- The `out_of_workspace` path resolution is not trivially bypassable.
- No secrets appear in any log.
- Kill latency and the budget overshoot bound are measured, not assumed.

---

## Phase 3: Scorer

**Exit check:** *Scorer flags known-bad snapshot, passes known-good.*
Concretely:
- `lrae score` on `fixtures/snapshots/known_bad` emits C > 0 (the `vendor_unchanged` probe) and R > 0, along with their hazards.
- On `known_good` it emits P = 1.0, R = 0, C = 0, and no hazards.
- All seven metrics are present for both.
- Re-scoring is deterministic (X comes from the judge cache).

**Tests first**
- `tests/unit/scorer/`:
  - `test_p_hidden.py`, `test_r_regression.py`, `test_d_defects.py`.
  - `test_c_constraints.py`: each probe has violating and clean mini-repos, including the stdlib, first-party and third-party import cases, a `pip freeze` drift case, and an endpoint added with and without a test.
  - `test_w_repeat.py`: a synthetic git history with known churn.
  - `test_s_cost.py`: accepted commits, the baseline, and the zero-commit rule.
  - `test_x_judge.py`: a fake judge runner in place of the `claude -p` call; schema validation, retry, null handling, median of 3 with the spread recorded, and untrusted-data wrapping.
- `tests/unit/scorer/test_hazards.py`: every row of spec §8.4, including attribution to the first offending commit and the once-per-dimension rule.
- `tests/integration/test_scorer_hardening.py` (local):
  - A snapshot containing a malicious `conftest.py` that forces passes, and a `tests/` directory that deletes assertions, **does not** change P or R.
  - The agent app's failure to start produces P = 0 with a logged reason.
  - No scorer process outlives scoring.
  - The temp copy is deleted.
- `tests/integration/test_known_snapshots.py` (local): the exit check.

**Tasks**
1. **Hidden tests** `fixtures/tasks/export_csv/hidden/`: 12 black-box HTTP acceptance tests for `GET /export`, covering:
   - CSV content-type and header row, and correct rows;
   - pagination params and limits, and page boundaries;
   - per-user rate limiting: allowed, then 429, with users isolated from each other;
   - one audit-log entry per export, and none on rejected requests;
   - auth required;
   - CSV escaping of commas, quotes and newlines.
   
   The interface the tests assume MUST match `prompt.md`. Get a human review of the prompt/test pairing.
2. A **reference solution** becomes `fixtures/snapshots/known_good` (P must be 1.0). Then `known_bad` = known_good plus an edit to `vendor/` plus a change that breaks one seed test.
3. `scorer/requirements.txt` and `tools/scorer-venv` (built by `lrae install-scorer`).
4. The metric modules, `run_checkpoint.py`, `hazards.py`, the judge (prompt template, response cache, isolated `claude -p` subprocess with tools disabled), and the `lrae score` CLI.
5. Hook the asynchronous scorer queue into the orchestrator. Check that the < dt/2 throughput target holds.

**Out of scope:** threshold calibration; ladder tasks.

**Reviewer checklist:**
- The hidden tests match the prompt's stated interface.
- The gaming-resistance tests fail when the hardening is removed.
- The judge prompt is reviewed.

---

## Phase 4: Pilot (design §4.2)

**Exit check:** *Metrics are stable across repeats*, plus every item of spec §13. "Stable" uses the definition in spec §15 Q3, unless the reviewer amends it.

**Tests first**
- `tests/unit/analysis/test_ingest.py`: JSONL→SQLite is complete, idempotent, and rebuild-identical.
- `tests/unit/analysis/test_survival.py`: Kaplan–Meier and Greenwood checked against a published worked example; bootstrap seeded and deterministic; median "not reached"; headline-X computation (D-11).
- `tests/unit/analysis/test_trends.py`: aligned per-checkpoint series and medians.
- `tests/unit/report/test_dashboard.py`: the dashboard builds from a synthetic SQLite with no network access, and every figure exists.
- `tests/integration/test_pilot_pipeline.py` (local): a scripted end-to-end pilot (2 repeats × 6 checkpoints at a 1 min dt) followed by `ingest` and `dashboard` gives 7 metrics × 6 × 2 with no nulls.

**Tasks**
1. `analysis/ingest.py`, `survival.py`, `trends.py`; `report/charts.py`; dashboard v1 (`lrae dashboard`).
2. **Dry run** (api): one 15 min config-A run to estimate $/hour and set `per_run_usd` with ~1.5× headroom. Get budget approval for the pilot.
3. **Pilot** (api): 2 repeats × config A × 60 min, dt = 10 min, plus both canary runs.
4. **Determinism check:** re-score every pilot snapshot and diff the results.
5. **Calibration:** propose `repeat_work_ratio`, `cost_per_commit_multiplier` and the baseline (and whether D should become a hazard) in `docs/calibration.md`. Changes go into a new spec (new `spec_hash`). Optional: one 2 h run.
6. Add a minimal `lrae report --pdf` stub so that acceptance item 5 holds.

**Reviewer checklist:**
- The pilot actually exercised the hazards.
- The calibration is justified by the data.
- Cost accounting matches real usage within 2%. With a Console API login, compare against the bill; with a subscription login, cost is an estimate, so compare token counts.

---

## Phase 5: Full runs

**Exit check:** *Data complete, outliers explained.*
Concretely:
- Every (task class × config × repeat) cell has N ≥ 5.
- Every run has all checkpoints scored with no null metrics, or a documented reason.
- Any run outside 1.5×IQR of its cell on TTFH or cost is explained in `docs/outliers.md`.

**Tests first**
- `tests/unit/runner/test_configs.py`: behavior of the B, C, D and E loop drivers, using the scripted runtime and a fake clock.
- `tests/unit/analysis/test_compare.py`: Poisson rate CIs, Δ-median, cost overhead, log-rank.
- `tests/unit/analysis/test_completeness.py`: a missing cell, a missing checkpoint or a null metric is flagged.
- Per ladder task: `tests/integration/test_known_snapshots_<task>.py`.

**Tasks**
1. Implement configs B–E (spec §4.3, D-4).
2. Author the ladder tasks L2 and L3. Each needs a seed repo, prompt, constraints, probes, hidden tests (human-reviewed), and known-good/known-bad snapshots.
3. `lrae run` matrix mode with resumable scheduling and a randomized order (seeded). Runs execute sequentially on this machine by default. Matrix wall-clock time is roughly the Σ of run durations, so plan for multi-day execution.
4. A cost and wall-clock estimate for the full matrix, then **owner approval**, then launch. Monitor with the dashboard and resume interrupted runs.
5. The completeness checker and outlier report.
6. Escalate to the next ladder tier only after the previous tier's data is complete.

**Reviewer checklist:**
- Configs differ only in loop-driver behavior.
- Resumed and interrupted runs are listed.
- Any `harness-access` kills are investigated; they invalidate the affected cell's data.
- Spend stayed within budget.

---

## Phase 6: Report

**Exit check:** *Reviewed by sponsor.*
Before it goes to the sponsor, `lrae report <experiment_id> --pdf` must produce a 2–3 page PDF from the metrics store with no manual steps, and every number in it must trace to a query.

**Tests first**
- `tests/unit/report/test_queries.py`: each report query returns the expected values on a synthetic store.
- `tests/unit/report/test_headline.py`: headline generation, including the "bound never reached" and "insufficient data" cases.
- `tests/unit/report/test_caveats.py`: if any run used `isolation.mode: local`, the caveats section states that runs were not OS-isolated.
- `tests/integration/test_pdf_build.py` (local): the PDF builds via headless Chrome, has 2–3 pages, contains all five section headings, and has no unrendered Jinja tokens.

**Tasks**
1. `report/queries.py`, `exec_report.html.j2` (print CSS), `build.py` (Chrome `--headless --print-to-pdf`).
2. The sections from design §5, with an appendix listing spec hashes, run IDs and the isolation mode.
3. A plain-language pass for a non-technical executive.
4. Sponsor review, and fold in the feedback.

**Reviewer checklist:**
- The caveats are stated plainly, including local-mode isolation.
- No number is hand-typed.
- The recommended operating limit follows the D-11 rule.

---

## Phase 7 (optional): Docker isolation mode

**When:** not needed for this study, since the owner accepted local-mode results for the report (D-14). Do it only if a `harness-access` or `home-secrets` kill shows the local-mode gap matters in practice, or if a later study needs enforced isolation.

**Exit check:** the Phase 1–4 local-mode test suites pass unchanged with `isolation.mode: docker`. In addition, the isolation tests prove that the agent **cannot** read harness files or reach non-allowlisted hosts.

**Scope** (the v0.2 design, now behind `isolation.mode: docker`):
- One container per run: non-root, `cap-drop=ALL`, `no-new-privileges`. Only the workspace and agent_home are mounted.
- A per-run Docker `internal` network, with an egress CONNECT-allowlist proxy.
- Managed settings baked into the image (root-owned, 0444), so the agent cannot disable OTel.
- A container-scoped credential, which brings back the dedicated credential from v0.2, since the host login would not be available inside the container.
- `docker pause`/`kill` in place of SIGSTOP/SIGKILL.
- The scorer runs in its own container with `--network none`.
- Image-content and mount-inspection tests.

The runner already isolates these points behind interfaces (`procs.py`, `workdir.py`, `preflight.py`), so this phase adds a backend rather than rewriting the runner.
