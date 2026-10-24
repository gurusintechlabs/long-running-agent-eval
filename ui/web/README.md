# LRAE UI web app

React + Vite + TypeScript single-page app for `lrae ui` (design: `docs/ui-design.md`). Charts are Apache ECharts with tree-shaken imports, code-split so only chart pages load it. Node >= 22 to build and test; running the UI needs no Node (the Python server serves `ui/web/dist`).

## Commands (run in `ui/web/`)

| Command | What it does |
|---|---|
| `npm install` | install dependencies (`node_modules/` is gitignored) |
| `npm run build` | typecheck, then build to `dist/` (gitignored) |
| `npm test` | Vitest + Testing Library (jsdom, canvas charts stubbed) |
| `npm run lint` | ESLint, including the UI-5 ban on raw HTML (`dangerouslySetInnerHTML`, `innerHTML`, `eval`, ...) |
| `npm run dev` | Vite dev server with hot reload; `/api` is proxied to `http://127.0.0.1:8765` (override with `LRAE_UI_TARGET`) |
| `npm run smoke` | headless-Chrome check of the built app (see below) |

## Using it

```
npm run build
python -m runner.cli ui            # prints http://127.0.0.1:8765/#token=...
```

Open the printed URL. The token lives in the URL fragment; the app reads it once, keeps it in memory and `sessionStorage`, and removes it from the address bar. A request without a valid token shows "open the URL printed by lrae ui".

For hot reload: start `lrae ui` (note its token), run `npm run dev`, and open `http://localhost:5173/#token=<that token>`.

## Smoke test

`node scripts/smoke.mjs [--url <printed url>] [--run <run_id>] [--shots <dir>] [--runs-dir <dir>]` drives headless Chrome over the DevTools protocol (no Playwright), visits Runs, a Run-detail page and a placeholder route, and fails on console errors, uncaught exceptions, failed requests or HTTP >= 400. `--shots` saves light, dark and narrow screenshots. Without `--url` it starts `lrae ui` itself (python from `$LRAE_PYTHON`, `<repo>/.venv`, or `python3`). If Chrome is missing it prints `SKIP` and exits 0 (set `LRAE_CHROME` to point at it).

## Layout

```
src/api/         typed client (token, 401 handling), response types, useAsync polling hook
src/app/         shell, auth gate, stale-store banner, re-ingest hook
src/components/  Badge, Card, Table, EmptyState/ErrorState/Spinner, Chart (lazy) + theme, design CSS
src/styles/      tokens.css (CSS variables, dark mode via prefers-color-scheme), base.css
src/views/<name>/ one folder per view: runs, run-detail (real), live, compare, launch, specs, review, reports (placeholders)
src/routes.tsx   route table (one line per view)   src/nav.ts  sidebar entries
src/test/        setup, helpers, fixtures/ (real API responses)
```

Adding a view: replace the folder's `index.tsx` content, keep the exported component name, and set `placeholder` to false in `src/nav.ts`. Untrusted text (run ids, evidence, test names, agent output) must only be rendered as React text children; lint enforces it. If you add ECharts chart types, register them in `src/components/chart/echarts.ts`.
