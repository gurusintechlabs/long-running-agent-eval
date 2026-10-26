# Phase U3 (views half): run-detail tabs

Frontend for the U3 data API (`docs/ui-api-events.md`). Branch `ui-w2-run-views`, built on `ui-manager`. All changes are in `ui/web/` plus this file; no Python was touched.

## Built
Run detail is now Overview | Timeline | Tests | Transcript | Events | Checkpoints (WAI-ARIA tabs, arrow/Home/End keys). The active tab and deep-link state live in the URL (`?tab=`, `cursor`, `t_s`, `k`).
- **Overview**: not-ingested card, metric charts, hazards (each hazard has "Open in transcript"). The checkpoints table moved to its own tab.
- **Timeline** (`timeline/`): one ECharts canvas with a shared time axis: cumulative est. cost and context-fill lines per checkpoint, plus lanes for checkpoints, stages/markers, compactions, hazards, behaviour, guardrail violations and the kill. Stage bands, legend toggle per lane, inside + slider zoom, toolbox box-zoom/reset, linked crosshair across both plots, one linked tooltip (HTML, every data string run through `escapeHtml`). Clicking a marker navigates to the matching transcript window (violation: `stream_cursor`; hazard/behaviour/stage: `t_s`; compaction: its cursor; checkpoint: `tab=checkpoints&k=`). Below the chart a keyboard-accessible incident list with the same links, lane chips and paging. Polls every 10 s for live runs without resetting zoom (`useStable`).
- **Tests** (`tests/`): a hand-drawn canvas heatmap (visible slice only, native scroll, sticky header with stage bands, time labels and checkpoint diamonds, tier headers, regression/recovery outlines, hover tooltip with test id/outcome/time/sha/stage). Tier chips, "only flipped / only failing", id filter, suite select. Stat tiles, pass-rate-over-time (overall, established, per tier) and per-stage bar charts, flips list with regression/recovery filter. `ingested:false` shows the re-ingest call to action; no per-test data and error states are handled.
- **Transcript** (`transcript/`): paged list (100 per page, "Load more", "Check for new items") with assistant text, tool calls (expand fetches `/transcript/item` for the full input and result), filters (search, tool chips with error counts, errors only, kind), around-windows for `cursor` / `t_s` deep links (20 before, 5 after, "Show 40 earlier", "Load later items", anchor highlighted and scrolled to), long text collapsed with expand and copy. `content-visibility: auto` keeps long pages cheap.
- **Events** (`events/`): merged event browser with source chips (with line counts), type filter (datalist from the summary, globs), raw-JSON search, paging with scan-cap handling, text-only collapsible JSON viewer, "Load the full event" through `/events/at` for truncated events, copy JSON.
- **Checkpoints** (`checkpoints/`): table with a "Diff and log" button per row; a modal drawer (focus trap, Esc, focus restore) with Diff (per-file sections, line numbers, +/- colouring, size-capped and dirty-flag notices, unavailable mirror), Commits and Scorer log.
- API types and clients in `src/api/{events,tests,timeline,query}.ts` (additive); `LazyChart`/`Chart` got an optional `onClick`; `echarts.ts` registers scatter, bar, zoom, toolbox, markArea. New shared test helper `mockRoutes`.

## Tested
- `npm test`: 8 files, 84 tests (was 38). New: model tests (links/cursor encoding, timeline events and option, tooltip escaping, heatmap flips/rows/bands/sizing for 5000 tests, series, diff parser) and component tests per tab with real-run fixtures (`src/test/fixtures/`, trimmed): not-ingested CTA, empty/error states, filters sending the right query, paging, expand tool call via item endpoint, cursor and `t_s` deep links (request params, highlight, `aria-current`), load full event, drawer (diff, commits, scorer log, dirty note, truncation, unavailable, missing log), tab keyboard navigation, hostile strings (`<img src=x onerror=alert(1)>` in test ids, timeline evidence, tool summaries/results, assistant text, diff lines, file paths, commit subjects, scorer log, event payloads) all as text.
- `npm run lint` clean; `npm run build` (tsc + vite) clean.
- `node scripts/smoke.mjs --url <real server> --run minidb-v3-pilot-haiku-A-r00-f47fe80e --shots <dir>` passes with no console errors or failed requests: loads every new tab by URL, expands a tool call, opens a transcript deep link and checks the highlight, opens an event JSON row, opens the checkpoint drawer and its scorer log. Screenshots (light, dark, 420 px) were inspected.

## What the screenshots showed, and fixes
Timeline and heatmap rendered correctly on the first pass. Fixed: the 156-row incident list made the page very tall (now a 460 px scroll box); the chart's axis names collided with the legend and toolbox (grids moved down); "recoverys" label; one "Copy" button per text/result block and "Copy cursor" per row was noisy (now small text links). The heatmap, drawer and event viewer needed no change. Full-page screenshots of the transcript show blank bands for off-screen items; that is `content-visibility: auto` and only affects captures.

## Deviations
- Transcript "virtualization" is paging plus `content-visibility: auto`, not a windowed list. The heatmap is a custom canvas, not an ECharts heatmap, for speed with thousands of tests.
- Timeline tooltip is a custom (escaped) HTML formatter, unlike the metric charts which use ECharts' default; it is covered by an escaping test.
- Cost and context series are per checkpoint (that is what the API gives). Sub-checkpoint resolution needs a backend change.
- Tabs unmount when left (filters and scroll are not kept; deep-link params are).

## Open issues
- Transcript live tailing is manual ("Check for new items"); SSE is U4.
- Heatmap has no keyboard cursor; the flips list and incident list are the accessible alternatives.
- The incident list shows at most the 500 violations and 1000 behaviour rows the server returns (a notice says so).
- Chart chunk grew 550 to 634 kB (more ECharts components); still lazy.
- Scorer log and diff are shown from `mirror.git` only; `dirty` checkpoints' uncommitted files are not served.
