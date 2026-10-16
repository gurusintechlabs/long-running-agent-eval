# Phase 2 Summary: Telemetry and guardrails

**Branch:** `phase-2-telemetry-guardrails` · **Spec:** v0.5 · **Date:** 2026-10-16

## Exit check status

> *Injected violation is detected and logged.* All cases use the scripted runtime on the real harness
> (orchestrator, OTLP receiver, monitor, kill switch): `tests/integration/test_guardrail_cases.py`.

| Case | Status | Test |
|---|---|---|
| (a) `rm -rf /` on the command channel → `guardrail.violation` + `guardrail.kill`, frozen < 2 s, KILLED, final snapshot | **Met** | `test_a_forbidden_command_is_killed_within_2s` |
| (b) `cat` of `fixtures/tasks/*/hidden` → `harness-access` kill | **Met** (also via `Read` with `..`) | `test_b_*` |
| (c) obfuscated write to `.claude/settings.json` caught by the effect channel | **Met** (logged; the rule's action is `log`) | `test_c_obfuscated_settings_write_caught_by_effect_channel` |
| (d) `emit_otel` cost past `per_run_usd` → BUDGET_EXHAUSTED | **Met**, plus a `per_run_tokens` cap | `test_d_budget_exhausted`, `test_d_token_cap` |
| (e) receiver stopped mid-run → `guardrail.telemetry_stalled`, agent paused | **Met** (process group observed in state `T`) | `test_e_telemetry_stall_pauses_agent` |

Both canary scripts (`fixtures/scripted/canary_forbidden.yaml`, `canary_harness_read.yaml`) are killed end to end (`test_canary_scripts_are_killed`); the Phase 4 pilot reuses them.

**Measured, not assumed** (5 rounds of (a), (b), (d)):
- Detection (tool call written to the stream log → violation event): 1–6 ms when the poll lands right, ≤ 206 ms worst case (poll interval 0.2 s).
- Detection → process group frozen: 34–64 ms.
- Budget overshoot: cap $0.05, requests of $0.02 → killed at $0.06, i.e. one in-flight request, matching the spec §7.2 bound.

## What was built

| Area | Files |
|---|---|
| Stream parsing | `telemetry/stream_parser.py`: `stream-json` → `tool.call`, `tool.result`, `assistant.text`, `session.init/result`, `context.compaction`. The runner writes the raw message and then the parsed events to `agent_stream.jsonl`. |
| OTel ingest | `telemetry/otlp_receiver.py`: duplicate batches dropped (bounded hash set, counted), `_otel_lag_ms` per record, `healthy()` |
| Counters | `telemetry/counters.py` `interval_counters` (tokens, cost, tool calls, context fill max/last, compactions with the >50% drop heuristic, turns, sessions, api errors, lag p95, cumulative variants); `telemetry/models.yaml` |
| Cost cross-check | `telemetry/crosscheck.py` (Σ OTel `cost_usd` per session vs `stream-json` `total_cost_usd`, 1%) |
| Policy | `guardrails/policy.py`: command regexes, path extraction from Bash text and tool inputs, resolution of `..`, `~`, `$HOME`, quotes, symlinks and `cd` across calls; effect-channel globs |
| Monitor | `guardrails/monitor.py`: command, effect, integrity and budget channels, stall detector, platform interruptions (repeated `api_error`, usage limit, auth, clock gap) |
| Kill switch | `guardrails/killswitch.py`: freeze → `guardrail.kill` (with latency) → final snapshot → SIGKILL + orphan sweep; first trigger wins |
| Wiring | `runner/orchestrator.py`: monitor per run; `_halt` for KILLED / BUDGET_EXHAUSTED / INTERRUPTED with a final snapshot marked `final: kill/budget/interrupt`; stall pause/resume; effect check at every checkpoint; `run.clock` event; manifest `end` now has `cost_usd`, `tokens`, `censored_reason`, and `policy_sha256` |
| Experiment budget | `lrae run` refuses to start a run once Σ estimated cost of finished runs with the same `spec_hash` reaches `budget.experiment_usd` (left open in Phase 1) |
| Canaries | `fixtures/scripted/canary_{forbidden,harness_read,budget}.yaml`; `@@REPO@@` is substituted by `ScriptedRuntime.render` |
| Contract | `docs/interfaces.md`: event types and payloads shared by Phases 2–4 |

## What was tested

`pytest` (default) and `-m local`: all green, ruff clean. The Phase 2 files hold 186 tests (93 policy, 35 monitor, 6 kill switch, the telemetry parsers and counters, 14 integration). The policy tests cover positive and negative examples per rule, `rm -rf ./build` allowed vs `rm -rf /`, `rm -fr ~`, `rm -r -f /`, `${HOME}`, symlinks into the repo, `..` chains, `cd` in one call then a relative read in the next, glob-style paths (`~/.ss?/id_rsa`), and the `{AGENT_STATE}/memory` exemption. A test checks that editing the policy file changes `spec_hash`. A secrets test checks that no `sk-ant-…` string reaches any event file.

## Unresolved / for review

1. **Telemetry-silence rule (proposed change, not silent):** spec §7.2 says *no OTel record for 60 s while the agent is active → pause*. A real agent sitting in one long tool call (e.g. a 2-minute test run) exports nothing and would be frozen. A frozen agent produces no records, so it would never resume. The orchestrator therefore pauses on **silence only when the receiver itself is down** (`OtlpReceiver.healthy()`). Lag > 10 s always pauses. A stall that lasts > 300 s ends the run INTERRUPTED (`censored_reason: telemetry_stalled`). Proposal: amend §7.2 accordingly after the Phase 4 dry run shows real export cadence.
2. **Real CLI payloads still unobserved:** `tool_use`/`tool_result` stream blocks, `compact_boundary`, and OTel `api_error`/`tool_result` are parsed from documented shapes (synthetic fixtures, marked as such). The first api run must capture real ones.
3. **Cost cross-check assumption:** each `claude -p` invocation (including `--resume`) is assumed to report only its own `total_cost_usd`. If the CLI reports a running session total, the check will flag it instead of passing silently.
4. **Effect channel gaps:** the "new files in HOME/TMPDIR" scan and the process-tree scan from §7.2 are not implemented. Only the `forbidden_paths` globs and the integrity hashes (harness settings, hidden tests) are covered. Known command-channel bypasses: paths built at run time (`$(printf …)`, base64, `eval`, Python string building). This is part of the accepted D-14 gap.
5. `network-tool` regex tightened so `~/.ssh/...` in a path is not reported as running `ssh`. `rm-rf-root` widened to flag orders/forms such as `-fr`, `-r -f`, `--recursive --force` and `${HOME}`. Ids, severities and actions are unchanged.
6. Resume cost double-counting (from Phase 1) is still open: OTel records are deduplicated within one receiver's lifetime, not across a resume.
7. **CLI version drift:** `claude --version` on this machine now reports **2.1.301** (Phase 1 recorded 1.0.126). `pilot.yaml` still pins 1.0.126, so pre-flight will refuse real runs until the spec is updated. Per D-17 the smoke test must be re-run after the update (it re-verifies flags, telemetry names and the `CLAUDE.md` behaviour). That needs spend approval.
8. D-7 (interruptions censor runs) is implemented as proposed.
