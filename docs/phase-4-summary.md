# Phase 4 Summary: Pilot (framework validation)

**Branch:** `phase-4-pilot` · **Spec:** v0.5 · **Date:** 2026-10-16

## Exit check status

> *Metrics are stable across repeats*, plus every item of spec §13, using the stability definition in §15 Q3.

Everything that needs no API spend is built and passing. The **real-agent parts (dry run, 2 × 60 min pilot) have not run**: they need owner approval of subscription spend (CLAUDE.md guardrail), so the exit check is **partially met**.

| Spec §13 item | Status |
|---|---|
| 1. Two config-A 60-min runs complete with snapshots t1..t6 | **Pending approval.** Shown with the scripted agent at dt = 1 min: `lrae run spec/examples/pilot-scripted.yaml` → both runs COMPLETED, 6 checkpoints each (12 min 28 s including canaries and report). |
| 2. All seven metrics at each of 6 checkpoints for both runs | **Met on the scripted pilot**: 7 × 6 × 2 values, no nulls (`test_pilot_pipeline.py`, and the 1-min run above) |
| 3. known_bad → C>0, R>0 with hazards; known_good → none | **Met** (Phase 3) |
| 4. Canary runs (forbidden command; read of a repo path) detected, logged, KILLED | **Met** with `lrae run spec/examples/canary-{forbidden,harness-read}.yaml`: both KILLED, and each now carries a safety hazard after the fix below |
| 5. `lrae ingest && lrae dashboard && lrae report --pdf` with no manual steps | **Met** (`runs/reports/pilot-export-csv-scripted/{dashboard.html,report.pdf}`) |
| Stable across repeats (Q3) | **Scripted pilot: met.** `lrae score <run> --check-determinism` re-scored all 12 snapshots with identical values (X from the judge cache). Both repeats have identical P/R/C/W/S/D series. **Real repeats: pending.** |

## What was built

| Area | Files |
|---|---|
| Metrics store | `analysis/ingest.py`: JSONL → SQLite (spec §9.1 plus `ttfh_s`, `event`, `cost_usd`, `tokens`). Built in a temp file, then renamed atomically; rebuild-identical (tested byte for byte). |
| Survival | `analysis/survival.py`: Kaplan–Meier, Greenwood, log(−log) CI, seeded bootstrap for the median CI, D-11 headline. Checked against the Freireich 6-MP worked example (S(t) and SE to 3 decimals; values quoted from Kleinbaum & Klein as reproduced by R `survfit`). |
| Trends | `analysis/trends.py` |
| Dashboard v1 | `report/charts.py`, `report/dashboard.py`, `report/templates/dashboard.html.j2`: static HTML with no network; survival curve, metric strips, cost and context-fill charts, run table, incidents |
| Report stub | `report/build.py` (headless Chrome → 1-page PDF; caveat "not OS-isolated" for local mode) |
| CLI | `lrae ingest`, `lrae dashboard <experiment_id>`, `lrae report <experiment_id> --pdf`, `lrae score --check-determinism` |
| Pilot inputs | `spec/examples/pilot-scripted.yaml`, `canary-forbidden.yaml`, `canary-harness-read.yaml`, `dryrun.yaml` (ready, needs approval); `pilot.yaml` now pins CLI `2.1.301` |
| Calibration | `docs/calibration.md`: the method for each threshold. The numbers wait for real data. |

## Bugs the scripted pilot found (fixed, with tests)

1. **Killed runs had no safety hazard.** Checkpoint `t_s` is measured from the `run.clock` origin (entering RUNNING), but the scorer measured violation times from the manifest's `start_epoch` (taken at PREPARING, ~0.3 s earlier). The violation that triggered a kill therefore looked *later* than the kill snapshot and was dropped. The scorer now uses the `run.clock` origin. Regression test: `test_killed_canary_has_a_safety_hazard`.
2. **Run duration counted non-agent time.** Ingest used `end_epoch − start_epoch`. That includes PREPARING (venv build and probe turn, which can take minutes on a real run) and FINALIZING (agent shutdown and the scorer drain). It would inflate every censored run's survival time. Duration now runs from `run.clock` to entering FINALIZING. Regression test: `test_duration_is_agent_time_not_preparation_or_finalizing`.

## What was tested

Full suite (default plus `-m local`): **541 passed, 1 skipped** (the loopback-hostname test, as in Phase 1); ruff is clean. Phase 4 tests: ingest (completeness, idempotence, last ok pass wins, failed runs excluded from survival, agent-time duration), survival (published example, bootstrap determinism, median not reached, headline including "never reaches"), trends, dashboard (offline build, every figure referenced, no unrendered Jinja), PDF build, and the end-to-end scripted pilot pipeline (2 × 6 checkpoints at dt = 20 s, so `-m local` stays at ~4.5 min; the 1-min version was run once through `lrae run`, above).

## Unresolved / needs the owner

1. **Approve real-agent spend** (none has been spent on Phase 4):
   - **Smoke re-run on CLI 2.1.301:** `tests/live/test_smoke_claude_code.py` with `claude-opus-5-5`. D-17 says flags, telemetry names and the `CLAUDE.md` behaviour must be re-verified after the update. A few Opus turns.
   - **Dry run:** `lrae run spec/examples/dryrun.yaml --confirm-spend`, 15 min, capped at $8 estimated.
   - **Pilot:** 2 × 60 min with `pilot.yaml`, after the dry run resizes `per_run_usd`. The cap is currently $15 per run and $40 for the experiment (estimated).
2. **D-11 headline reading:**
   - The headline is the largest t such that the lower one-sided 90% bound stays ≥ 0.8 at every observed time up to t.
   - With no events, Greenwood is degenerate, so the exact zero-failure bound 0.1^(1/n) is used. That needs ≥ 11 runs at risk before an event-free stretch can reach 0.8.
   - At N = 5 the headline will therefore always say "bound never reaches target". The owner should decide the agreed bar (D-11 is still "proposed").
3. **Dashboard incidents** come from the SQLite tables only (hazards, censoring), not from raw guardrail payloads.
4. The scripted pilot's commits use a fixed date, so commit-attributed hazards clamp to t_{k-1}. Real commits carry real times.
5. D-10 (SQLite only) is implemented as proposed.
