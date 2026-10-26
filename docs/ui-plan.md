# LRAE UI: phase plan (DRAFT, awaiting owner review of docs/ui-design.md)

One phase per session. Tests first. No phase launches a real agent run; control tests use the `scripted` runtime (no spend). Every phase ends with `docs/phase-U<n>-summary.md`.

Layout: `ui_server/` (Python package, added to `pyproject.toml`), `ui/web/` (Vite + React + TypeScript), `tests/unit/ui_server/`, `tests/local/ui/`, `ui/web/src/**/*.test.ts` (Vitest). CLI: `lrae ui [--port N]`.

## U1: Read API and ingest freshness
**Exit check:** against the real `runs/` directory, `GET /api/runs`, `/runs/{id}` and `/runs/{id}/checkpoints` return all 12 runs that have a manifest under `runs/` (the other entries there are `_failed/`, `reports/` and the db), including the v3 ones, with an `ingest/status` that says stale when logs are newer than `metrics.sqlite`; `pytest` green.
- Tests: synthetic runs dir and store; run-ID allowlist and traversal cases (UI-4); read-only DB (UI-8); Host/Origin rejection (UI-1).
- Finding (checked before coding): v3 runs are absent from `metrics.sqlite` because the store was last built on 2026-10-16, before they existed. Not a bug; a fresh `lrae ingest` finds all 12. So the list is built from manifests and the store only enriches it.
- Tasks: `ui_server/` app, `lrae ui`, token (UI-2), static file serving.

## U2: SPA shell, run list and run detail
**Exit check:** `npm run build` then `lrae ui` shows the run table and a run-detail page for `minidb-v3-pilot-haiku-A-r00-f47fe80e` with header, per-checkpoint metrics and hazards; Vitest green; one headless-Chrome smoke test loads both pages with no console errors.
- Charting is ECharts (owner choice). Components: RunTable, RunHeader, MetricCharts, HazardList.
- Tests: component tests on fixture JSON; a no-raw-HTML rule (UI-5) enforced by an ESLint rule plus a test with hostile strings.

## U3: Timeline, test heatmap, transcript
**Exit check:** for the haiku pilot run, a hazard on the timeline links to the exact transcript line, and the heatmap's flips match `analysis/degradation.py` output on the same run.
- Event paging endpoint with `after`/`limit` (10 MB streams must not be loaded whole). Transcript search and tool filters. Checkpoint diff from `mirror.git`.

## U4: Live view and safety panel
**Exit check:** with a `scripted` run in progress, the Live page shows new events, cost, context fill and checkpoints within 2 s, survives partial lines, and issues no writes of any kind (a test diffs the run directory before and after). Replaying the haiku pilot's `guardrail.jsonl` through the panel shows the 31 violations grouped by rule, the budget kill banner with the freeze delay, and 106 stall/resume pairs folded into one row; the canary runs (`canary-forbidden`, `canary-harness-read`) show a kill with evidence.
- SSE tail by byte offset; partial-line handling; "run ended" detection.
- Merged multi-source feed with a per-type renderer registry and a generic JSON fallback; noise folding; pause/jump-to-now/search.
- Safety panel as specified in design §7: status light, incident cards with rule explanation from the policy file, evidence highlight, context links, kill banner, budget meter, optional notifications.
- Tests: renderer snapshot tests per event type on real log samples (copied into `tests/fixtures/ui/`), hostile-string tests for evidence fields (UI-5).

## U5: Control with the spend gate
**Exit check:** from the UI, a `scripted` experiment can be validated, launched, stopped and resumed from tK; the spend-gate tests prove that a request without a matching estimate confirmation never reaches `--confirm-spend`, and that editing the spec invalidates it (UI-3).
- Subprocess runner on the runner's env builder (UI-7); one-at-a-time lock; process tracking from `manifest.json` (`harness_pid`); `clean`, `score`, `ingest` actions.
- One run at a time: launch is refused while a harness process from another run is alive.
- Real (`api`) runs are not exercised here. First real UI launch needs explicit spend approval from the owner (CLAUDE.md).

## U6: Spec editor and Review
**Exit check:** build a spec from the form editor (no hand-edited YAML), save it to the drafts dir, see it validate with the hash and run IDs, and see schema errors shown inline against the right field; every existing file in `spec/examples/` round-trips through the editor unchanged (same `spec_hash`); replay the B7 pilot label review end to end and reproduce the recorded owner decisions as append-only JSONL.

## U7: Compare and reports
**Exit check:** overlay two runs (metrics, hazards, cost); survival chart matches `analysis/survival.py` on the same data; "rebuild report" produces the same PDF as `lrae report --pdf`.

## Budget and risk
- No API spend in any phase. Largest risk: the Python/Node split (build step, two test runners). Mitigation: `make ui` style script and a CI-free local check; the built bundle is not committed.
- Second risk: serving a 37 MB-per-run log. Mitigation: always page by offset, never parse whole files in the request path, cache an events index per run.
