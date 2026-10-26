# LRAE UI: local management frontend (owner-approved 2026-10-24)

Status: v0.2, 2026-10-24. **D-19 and D-20 approved by the owner.** The UI is the human's primary way to work with the harness (manager, one run at a time). Owner choices recorded: **full manager** scope, **React/Vite SPA**, **live tailing of running runs**, ECharts, one run at a time, form-based spec editor (see §8).

## 1. Why

Today a run is 37 MB of JSONL, 14 checkpoint snapshots and a SQLite cache, viewed through a static Jinja2 dashboard. That shows aggregates but cannot answer "what was the agent doing at hour 3, when did the tests start flipping, and why did it stop?". It also cannot start, stop or label anything without the terminal.

## 2. Spec conflicts to resolve first (owner sign-off needed)

| Conflict | Where | Proposal |
|---|---|---|
| "A live web dashboard server" is a v1 non-goal | spec §1 | New decision **D-19**: a local-only UI server is in scope for the UI track (phases U1-U7). The v1 report path (static dashboard, PDF) is unchanged. |
| "Small Python libraries allowed; no services" | D-3 | The UI server is a foreground process started by `lrae ui`, bound to 127.0.0.1, with no daemon and no state of its own. It is not a service the harness depends on. Nothing in runner/, scorer/ or telemetry/ may import it. |
| Stack has no Node | CLAUDE.md | **D-20**: Node >= 20 and npm are needed to *build* the SPA only. The built bundle (`ui/web/dist`) is served as static files by the Python server, so running the UI needs no Node. `node_modules/` and `dist/` are gitignored. |
| "Observe, don't interfere" preference | memory | Live view only reads logs. It never probes the agent session. Control actions are limited to the existing CLI verbs (see §6). |

## 3. Architecture

```
browser (React/Vite SPA, TypeScript)
   |  HTTP JSON + SSE   (127.0.0.1 only, per-session token)
ui_server/   (Python, FastAPI + uvicorn; read-mostly)
   |-- reads  runs/metrics.sqlite  (opened read-only)
   |-- reads  runs/<run_id>/events/*.jsonl, manifest.json, scorer/, snapshots/
   |-- calls  `lrae validate | run | resume | ingest | score | clean | report`  as subprocesses
```

Rules:
- **The server is a thin adapter.** It re-uses `analysis/` and `report/` functions for numbers and charts' data, and the `lrae` CLI for every action. It does not reimplement scoring, ingest or run control, so there is one code path.
- **Metrics still come from logs (working rule 5).** SQLite stays a derived cache. The server reports its freshness (newest ingested event vs newest event on disk) and keeps the store current by running `lrae ingest` itself when new scores land (auto-ingest, owner 2026-10-25; `--no-auto-ingest` falls back to the "re-ingest" button). Known today: the v3 runs are missing from `runs` in `metrics.sqlite`.
- **Charts are drawn in the browser from JSON** (a small library such as uPlot or Recharts, decided in U2). The matplotlib PNGs remain for the PDF report.
- **The server keeps no state.** Pending launches, UI preferences and review labels are files under `runs/` or `ui_state/` (gitignored), so deleting it loses nothing the logs do not have, except human review labels (which are written as append-only JSONL, rule 5).

## 4. Views

1. **Experiments / runs**: table of runs (state, model, duration, cost, tokens, hazards, last checkpoint), filter and sort; stale-ingest banner.
2. **Run detail**:
   - header: spec hash, model, CLI version, seed commit, isolation mode, end reason (from `manifest.json`)
   - timeline lanes: checkpoints, stages, hazards, guardrail events, compactions, context fill and cost lines over time
   - metrics per checkpoint (P, R, S, D, C, W, X and the rest)
   - test outcome heatmap with flips and regressions
   - hazard list with evidence
   - per-checkpoint panel: scorer log, commit list, diff versus the previous checkpoint (from `mirror.git`)
3. **Transcript**: agent stream, filterable by tool, with search; jump from a timeline event to the transcript line.
4. **Live**: for a running run, the same page with SSE-tailed logs, a "now" marker, budget burn against caps and guardrail alerts.
5. **Compare**: two or more runs overlaid (metric series, hazards, cost), plus survival across a config set (reuses `analysis/survival.py`).
6. **Launch / control**: pick a spec, `lrae validate`, show the pre-flight result and the **estimated spend**, then start (see §6). Stop, resume from tK, clean, re-score.
7. **Specs**: view, edit and validate experiment specs (writes only under `spec/examples/` or a configured drafts dir, never in `runs/`).
8. **Review**: the label-review workflow used for the B7 pilot (draft labels in, owner confirm/reject out, written as append-only JSONL). The exact data format is taken from `docs/phase-B7-summary.md` in U6.
9. **Reports**: open or rebuild the dashboard and PDF.

## 5. API sketch (all JSON; `/api/...`)

Read: `GET experiments`, `runs`, `runs/{id}`, `runs/{id}/checkpoints`, `runs/{id}/metrics`, `runs/{id}/tests`, `runs/{id}/hazards`, `runs/{id}/events?source=&type=&after=&limit=`, `runs/{id}/stream` (SSE), `runs/{id}/checkpoints/{k}/diff`, `ingest/status`.
Write (each maps to a CLI verb): `POST specs/validate`, `runs` (launch), `runs/{id}/stop`, `runs/{id}/resume`, `ingest`, `runs/{id}/score`, `clean`, `reports/{exp}`.

## 6. Security requirements (each gets an automated test)

The UI sits on the trusted harness side but displays untrusted agent output and can spend money.

- **UI-1 Local only.** Binds 127.0.0.1; refuses other `Host` headers (DNS rebinding) and other `Origin`s on writes.
- **UI-2 Token.** A random per-start token is required on every write and on SSE. It is printed in the terminal URL and never stored.
- **UI-3 Spend gate.** Launch and resume never pass `--confirm-spend` unless the request carries a confirmation that echoes the server-computed estimate (cost cap, token cap, wall-clock) that the UI displayed. Changing the spec between display and confirm invalidates it (spec-hash match). `api`-marked tests remain terminal-only (CLAUDE.md guardrail).
- **UI-4 No path escape.** Run IDs and file names are matched against a strict allowlist and resolved inside `runs/`. Symlinks are not followed out of it.
- **UI-5 Untrusted content is text.** Transcripts, commit messages and test names are rendered as text; no `dangerouslySetInnerHTML`, no Markdown HTML. A CSP forbids inline script.
- **UI-6 Nothing into the work dir.** The server never writes under any `isolation.work_dir`, never serves scorer or hidden-test files from a run that is still in progress to anything but the local user, and never reads or copies the Claude login or other `~/.claude` projects.
- **UI-7 Scrubbed subprocess env.** CLI subprocesses are started from the same env builder the runner uses (D-15), not the server's environment.
- **UI-8 Read-only DB.** SQLite is opened `mode=ro`; only `lrae ingest` writes it.

## 7. Live feed and safety panel

The Live page and the run-detail "Events" tab share one renderer. Every log line has the same envelope (`ts`, `source`, `type`, `seq`, `payload`), so display is a registry of per-type renderers with a generic JSON fallback.

**Feed (not a raw log dump):**
- One merged, time-ordered stream across `agent_stream`, `orchestrator`, `guardrail`, `counterpart`, `env`, `scorer` and `otel`, with source chips to toggle each.
- Per-type cards, for example: tool call (name, short input, result status, duration), assistant text, checkpoint (k, commit, scorer queued/finished), stage delivered, turn start/end, state change, counterpart message (what the "ops" colleague said), budget update. Long content is collapsed with "expand"; the full text is always one click away.
- Noise folding: runs of `telemetry_stalled`/`telemetry_resumed` pairs (106 of each in the haiku pilot) collapse into one "telemetry silent 60 s x N" row.
- Pause/resume scrolling, "jump to now", search, and a link from any row to its place in the transcript.

**Safety panel (always visible while a run is live, and on run detail):**
- A status light: **clear / warnings / violations / killed**, driven by `guardrail.violation` and `guardrail.kill` events.
- A list of incidents, newest first, each as a card with: the rule (`rule_id`), severity, action taken (`log` or `kill`), channel (`command`, `effect`...), a plain-language explanation of what the rule protects (taken from the policy file, so it is never hand-typed), the **evidence** (the offending command or path, highlighted), the time and run offset, and a link to the surrounding transcript lines (20 before, 5 after).
- Grouping by rule with counts (the haiku pilot has 31 violations, mostly `other-outside` warnings), so a burst of one benign warning does not bury a `harness-access` kill.
- Kill banner: when `guardrail.kill` arrives, show the rule, the reason, the detection-to-freeze delay (`detect_mono_ns` to `frozen_mono_ns`) and the budget figures.
- Budget meter (cost and tokens against `per_run_usd` / `per_run_tokens`) that turns amber then red as it nears the cap. Optional browser notification and tab-title badge on a new violation or kill, off by default.
- Everything here is observation. It never blocks or probes the agent ([[observe-dont-interfere]] preference).

## 8. Decisions taken in review (owner, 2026-10-24)

- **One run at a time** from the UI. Launch is refused while another harness process is alive (`manifest.json` `harness_pid` check).
- **Spec editing is in scope.** Form-based editor over the spec schema (`spec/schema.py`), with the YAML view as a secondary tab. Writes go to a drafts dir; launching needs a saved spec that passes `lrae validate`. The editor offers fields, defaults and inline validation messages from the pydantic schema, so no one has to hand-edit YAML.
- **Charts: Apache ECharts** (time series, heatmap, survival curves and the timeline in one library, with zoom/brush and linked tooltips). Tree-shaken imports to keep the bundle small.
- **Charting and safety display requirements** above are accepted.
- Defaults I chose (change if you disagree): label-review writes go to `runs/<id>/review.jsonl` (append-only); the UI never edits files under `runs/` other than that.

## 9. Resolved / non-goals

- D-19 and D-20 approved (owner, 2026-10-24).
- **Notification sounds and browser notifications are a non-goal.** The safety panel is visual only (status light, incident cards, tab-title badge at most).
- Implementation note (U1): `runner/cli.py` registers `lrae ui` through `ui_server/cli.py`, a stdlib-only module that imports the server lazily. Nothing else in `runner/`, `scorer/` or `telemetry/` imports `ui_server`, and the server's dependencies (FastAPI, uvicorn) are an optional `ui` extra.
- Implementation note (U1): the token is required on **every** `/api/*` request (reads included), which is stricter than §6 UI-2. The SPA gets it from the URL fragment (`#token=...`), which is never sent to the server.
- Implementation note (U1): the run list is built from the manifests on disk (always current, including a run in progress) and enriched from `metrics.sqlite` when the run has been ingested, so a stale store never hides a run.
