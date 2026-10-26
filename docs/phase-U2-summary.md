# Phase U2: SPA shell, run list and run detail

**Exit check (met):** `npm run build` then `lrae ui` serves the run table and the run-detail page for `minidb-v3-pilot-haiku-A-r00-f47fe80e` (header, checkpoints, hazards panel); Vitest is green (38 tests); the headless-Chrome smoke script loads Runs, run detail and a placeholder route against the real `runs/` with no console errors or failed requests.

## Built (`ui/web/`)
- Vite + React 19 + TypeScript, react-router (client routes; the server's SPA fallback serves them), ECharts 6 with tree-shaken imports (line chart, grid, tooltip, legend, markLine, dataZoom-inside, canvas) code-split into a lazy chunk. Bundle: app 292 kB (93 kB gzip), chart chunk 550 kB (185 kB gzip), loaded only on pages with charts.
- Dev proxy `/api` -> `http://127.0.0.1:8765` (rewrites Origin so the server's origin guard accepts it).
- ESLint bans `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function` (UI-5), and a test lints probe snippets to prove the rule fires.
- Shell: sidebar (top bar on narrow screens), routes Runs, Run detail, Live, Compare, Launch, Specs, Review, Reports. Placeholders are labelled "soon / Not built yet" and each lives in `src/views/<name>/` (Live also routes `/live/:runId`).
- API client `src/api/`: token read from `#token=`, kept in memory + sessionStorage, stripped with `history.replaceState`; `X-LRAE-Token` on every call; 401 or no token shows the "Open the URL printed by lrae ui" screen (no request is sent without a token); `ApiError` carries status and server detail; a failed ingest (HTTP 500 `{ok:false,output}`) is returned as a result. `useAsync` hook with optional polling.
- Stale-store banner (polls `/api/ingest/status` every 15 s) with "Re-ingest now" (POST `/api/ingest`), result/output display, and a data-version bump so open views reload after a successful ingest.
- Runs view: sortable table (state badge, live pulse, experiment, model, start, duration, "Est. cost", tokens, hazards, checkpoints, ingested), search, state / ingested / live-only filters, group-by-experiment using `/api/experiments`, empty/error states, polling every 4 s while any run is live. Cost is labelled "estimated (API-equivalent)".
- Run detail: header (spec hash, model, CLI version, seed commit, isolation mode, safe mode, end state/reason, ttfh), metric small-multiples (P, R, D, C, W, X, S by default, others via the picker, hazard markers), checkpoints table (with metric columns when ingested), hazards list, and a "Not ingested yet" panel with re-ingest. Polls while live.
- Component kit: Badge/StateBadge, Card, Table (sortable, aria-sort), EmptyState, ErrorState, Spinner, Chart + LazyChart + theme hook (re-reads CSS tokens when the OS scheme changes), tokens.css with light/dark via `prefers-color-scheme`.
- `scripts/smoke.mjs` (Chrome DevTools protocol over Node's built-in WebSocket, no Playwright); `README.md`.

## Tested
- `npm test`: 6 files, 38 tests: token parsing/stripping/storage, header and 401 handling, URL encoding, ingest failure; Runs filter/sort/group/hostile strings/live polling; run detail from real fixtures (header, 7 charts, picker, checkpoints, hazards, hostile evidence, not-ingested + re-ingest, 404); 401 and no-token screens; stale banner + re-ingest; ESLint raw-HTML rule; chart option builder (no custom HTML tooltip formatter).
- `npm run lint` and `tsc --noEmit` (inside `npm run build`) are clean.
- `node scripts/smoke.mjs --url <real server> --run minidb-v3-pilot-haiku-A-r00-f47fe80e --shots <dir>` passes; also run for `minidb-v2-early-A-r00-338286d0` (ingested: charts render). Screenshots (light, dark, 420 px) were inspected and polished (run-id column no longer wraps, safe-mode object rendering fixed).
- Fixtures in `src/test/fixtures/` are real `lrae ui` responses (read-only against the main checkout's `runs/`).

## Findings
- The real store is stale (8 of 12 runs ingested), so the exit-check run (haiku v3) is **not ingested**: the UI shows the stale banner and the "Not ingested yet" state, with checkpoints from the logs but no metric charts or hazards. Charts were verified on the ingested `minidb-v2-early` run. Nothing was re-ingested (it would write to the main `runs/`).
- Real manifests carry `safe_mode` as `{enabled, reason}`, not a boolean; the UI handles object, boolean and absent.

## Deviations from the design
- Charts use ECharts' default tooltip (which escapes text) instead of a custom formatter, to keep UI-5 intact.
- `safe_mode` shown with the recorded reason. Nav shows "soon" tags on placeholder views. The dataZoom component is registered but no zoom UI is exposed yet.

## Unresolved / for later phases
- No backend change needed. Possible U3 improvements: run-detail test heatmap and timeline, a per-checkpoint hazard link, server-side `metrics` endpoint (currently metrics ride on `/checkpoints`).
- Chart chunk is 550 kB; if it matters, switch ECharts to the leaner `echarts/lib` imports or register fewer components.
- Browser-tab title is set per page but not announced to screen readers on route change (focus management is a later polish item).
- Dev proxy assumes the default port 8765.
