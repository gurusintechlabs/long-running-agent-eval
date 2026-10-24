# Phase U7 summary: Compare and Reports

Branch `ui-u7-compare` (from `origin/ui-manager`). API reference: `docs/ui-api-compare.md`.

## Built
- Backend (new files only): `ui_server/routes/compare.py` (`GET /api/compare`, `GET /api/survival`), `ui_server/routes/reports.py` (`GET /api/reports`, `GET /api/reports/{exp}/file`, `POST /api/reports/{exp}/rebuild`).
- Survival calls `analysis.survival` (`survival_inputs`, `summarize`, `headline_text`); the rebuild runs the real CLI verbs as a subprocess.
- Frontend: `ui/web/src/views/compare/` (run picker with `?runs=` preselect, metric overlay with metric picker and x axis by run time or checkpoint, hazard markers, cumulative-cost and context-fill overlays, delta table vs the first run, hazard table, survival panel with KM step curve, CI band, censor ticks, D-11 limit marker, summary table) and `ui/web/src/views/reports/` (per-experiment cards, sandboxed dashboard preview, PDF in a new tab, rebuild buttons with progress and output tail, stale-store hint with re-ingest, Chrome-missing message). Shared files touched additively: `api/index.ts` (one export line), `nav.ts` (two `placeholder` flags removed), `app/app.test.tsx` (the placeholder test now checks navigation to Compare), `scripts/smoke.mjs` (Compare and Reports steps replace the placeholder check).

## Tested
- `pytest tests/unit/ui_server/test_compare_api.py test_reports_api.py` (default marks): see counts in the final report; plus `-m local` for the real-runs tests (`test_compare_real.py`, read-only on `LRAE_REAL_RUNS`) and the real-Chrome PDF test.
- Security tests: token on GET and POST, foreign Origin 403 on POST, traversal in file names and experiment ids, symlinked file, figures dir and experiment dir, CSP sandbox on HTML, scrubbed env, single flight, stale 409, no-Chrome 424.
- End to end: a real `lrae dashboard` through the endpoint in a temp runs dir (output byte-identical to the plain CLI), and a real PDF whose page count and size match `lrae report --pdf`.
- Vitest 108 tests (new: compare, reports), ESLint (UI-5 rule on), `tsc`, `npm run build`, `npm run smoke` against the real runs dir.

## Deviations and notes
- "Rebuild produces the same PDF": PDFs embed timestamps, so the test compares page count and size (<2%) with the plain CLI, and the dashboard HTML byte for byte.
- `GET /api/reports` also lists ingested experiments with no reports yet (so a first build is possible).
- Dashboard HTML is shown through `srcdoc` with figures inlined, not by pointing an iframe at the API (the token cannot ride on an iframe src). The "new tab" option is offered for the PDF only, since a blob page would share the app origin.
- The app-wide CSP middleware overwrites response headers, so the sandbox CSP is applied by an extra outermost ASGI middleware registered from `reports.py`; `app.py` is unchanged.
- The delta table hides the ~60 `lrae.*` detector metrics behind a button.

## Open issues
- With a single run per experiment (most real data) the KM curve is one step and the CI is uninformative; the UI says so for n < 5.
- Survival chart cannot filter by hazard dimension in the UI yet (API supports `dimension`).
- Hazard labels overlap when hazards are close in time.
