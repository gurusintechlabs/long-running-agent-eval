# LRAE management UI: overall summary (branch `ui-manager`)

Built autonomously on 2026-10-24/25 from docs/ui-design.md and docs/ui-plan.md with parallel subagents (one worktree and branch each, merged into `ui-manager`), plus an independent adversarial security review whose findings were fixed (docs/phase-UH-hardening-summary.md). **No API spend occurred and no real agent run was started.** Owner decisions: full manager, one run at a time, React/Vite + ECharts, live tail, form-based spec editor, rich safety panel, no notification sounds (D-19, D-20).

## Run it
```
.venv/bin/pip install -e '.[ui]'          # FastAPI, uvicorn, httpx (already in .venv)
cd ui/web && npm ci && npm run build      # once, and after UI changes (dist/ is gitignored)
.venv/bin/lrae ui                         # prints http://127.0.0.1:8765/#token=... (new token every start)
```
The token is in the URL fragment; open the printed URL. If the store looks stale, use the banner's "Re-ingest now" (the v3 runs were only "missing" because `runs/metrics.sqlite` dated from 2026-10-16; it has since been re-ingested: 12 runs).

## What exists (phase -> branch -> docs)
| Phase | What | Docs |
|---|---|---|
| U1 | Read API, stale-store status, token/Host/Origin guard, read-only SQLite | phase-U1-summary |
| U2 | SPA shell, Runs table, Run detail (metrics, hazards, checkpoints) | phase-U2-summary |
| U3 | Events paging, transcript, test heatmap data, timeline, checkpoint diff; views for all of them | ui-api-events, phase-U3-data-summary, phase-U3-views-summary |
| U4 | Live SSE tail, live snapshot, safety panel data, feed normaliser; Live/Replay view and SafetyPanel (also on run Overview) | ui-api-live, phase-U4-data-summary, phase-U4-views-summary |
| U5 | Launch preview/launch with nonce + typed spend confirmation, stop/kill/resume/score/clean; Launch view, control bar, run actions | ui-api-control, phase-U5-data-summary, phase-U5-views-summary |
| U6 | Spec form editor (schema-driven, validate/save drafts to `spec/drafts/`), review queue/decisions (`runs/<id>/review.jsonl`) and views | ui-api-specs, phase-U6-data-summary, phase-U6-views-summary |
| U7 | Compare overlay, survival (reuses analysis/survival.py), report list/serve/rebuild; views | ui-api-compare, phase-U7-summary |
| UH | Security hardening after independent review | phase-UH-hardening-summary |

## Verified
- `pytest` (default suite) green; `-m local` for ui_server and the three real-run integration files green; `ruff` clean.
- `ui/web`: 297 Vitest tests, ESLint (raw-HTML ban) and `tsc` clean; `node scripts/smoke.mjs --run minidb-v3-pilot-haiku-A-r00-f47fe80e` (headless Chrome against the real `runs/`, read-only) passes: Runs, run-detail tabs, deep links, Launch preview (scripted only), Specs editor, Review, Compare, Reports, haiku replay (31 incidents, budget kill, folded stalls) and both canary kills.

## Decisions I took (please review)
- Token required on every `/api/*` request, not only writes (stricter than the design); delivered via URL fragment.
- `spec/drafts/` is **not** gitignored (specs must be reproducible and committable).
- Re-ingested `runs/metrics.sqlite` (derived cache, rebuilt from logs) so all runs have charts.
- UI cannot launch a spec that names files outside the repo (a spec with `hidden_tests: /usr` made preview walk the disk); the CLI still can.
- A UI "Stop" ends the run as `FAILED` after finalizing (the CLI has no signal handler); a clean "stopped by user" state needs a runner change.

## Open items / proposals needing runner or spec changes (not made)
- `--expect-spec-hash` on `lrae run/resume` (closes the spec swap race), record `harness_argv`/create time/`repo_root` in the manifest, refuse starting a run when `spent + per_run` exceeds the experiment cap, a `--runs-dir` option, no-alias YAML loading and size cap in `spec.loader`, `O_NOFOLLOW` in `telemetry.counters`.
- The first real (`claude_code`) launch from the UI is deliberately untested; it needs your explicit spend approval.
- Cost/context charts are per checkpoint (finer series would need an index over `otel.jsonl`); the chart chunk is ~630 kB (lazy); transcript uses paging + `content-visibility`, not a windowed list; diffs show `mirror.git` only (dirty checkpoints' uncommitted files are not shown).
