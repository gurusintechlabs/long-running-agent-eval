# Phase U4 (backend half): live tail, live status, safety panel data

Branch `ui-u4-live` (from `ui-manager` 9d8da0c). The React views are built later by another agent from
`docs/ui-api-live.md` (every endpoint with example JSON, cursor format and framing).

**Exit check (met, backend side):** with a scripted run in progress the stream delivers new events within 2 s, survives
torn lines and issues no writes (run directory diffed before and after); replaying the haiku pilot's `guardrail.jsonl`
through `/safety` shows the 31 incidents grouped by rule, the budget kill with its 26.7 ms freeze delay and the 106
stall/resume pairs folded into one item; both canary runs show a kill with evidence.

## Built
- `ui_server/tailer.py`: read-only tailing by byte offset (`FileTail`), time-ordered merge of every `events/*.jsonl`
  (`Merger`), torn-line holdback, oversize-line skip, late files, replaced-file restart, `locate_tail` (start so the
  stream opens with the last N visible events without reading 10 MB), cursor and ref helpers.
- `ui_server/feed.py`: display-event registry (about 40 per-type summarizers plus prefix and generic fallbacks), noise
  `Folder` for telemetry stall pairs, preview caps, text sanitising, `RunClock` (run-offset seconds), `/feed-schema`.
- `ui_server/feed_reader.py`: merger + filters + folder as one reader used by the stream and the paged feed.
- `ui_server/live_state.py`: incremental `/live` snapshot (cached per run by offsets), budget levels, burn rate, series.
- `ui_server/rule_docs.py`: rule explanations from the run's policy file (verified by hash, only inside the repo), with
  the fallback table keyed by `rule_id` (26 rules incl. orchestrator-added ones).
- `ui_server/safety_data.py`: incidents, kill attachment, groups, noise fold, budget events, scorer behaviour/hazard
  list, per-incident context windows from a sparse agent-stream index.
- `ui_server/routes/live.py` (`/stream`, `/live`, `/feed`, `/feed/event`, `/feed-schema`) and
  `ui_server/routes/safety_panel.py` (`/safety`, `/rules`). No existing file was edited.
- Fixtures `tests/fixtures/ui/runs/` (about 160 KB): full haiku guardrail, orchestrator, counterpart and env logs;
  excerpts of its agent stream, OTel and scorer; full guardrail, orchestrator and stream of both canaries. Home paths
  redacted (`/Users/USER`).

## Decision: framing
`fetch` + `ReadableStream` with `text/event-stream` framing and the token in the `X-LRAE-Token` header. `EventSource`
cannot send headers, and a token in the query string would land in history and logs. `Last-Event-ID` is honoured as a
request header and `?from=<cursor>` is the same thing. Heartbeat events, `caught-up`, `run.ending` / `run.ended` are
named events. Details and a client sketch are in `docs/ui-api-live.md` section 1.

## Tests (all `tests/unit/ui_server/` unless noted; no API spend, no real agent)
- `test_tailer.py` (17): torn lines, oversize, chunk-spanning lines, replaced files, symlinks refused, merge order and
  bounded buffering, late files, resume, `locate_tail`, boundary checks, read-only.
- `test_feed.py` (22): every real event (haiku, canary) renders with the stable shape, kinds per type, severities,
  debug levels, run offsets, folding (106 pairs to 1), preview caps, hostile strings (HTML, bidi override, NUL/ESC, SSE
  frame injection, 100 KB strings), summarizer failures isolated.
- `test_live_state.py` (11 + 1 local): numbers from logs not agent text, incremental reads, torn tail, restart on
  replaced log, budget levels, checkpoint ETA, real haiku totals equal the manifest (cost 15.00438819, 238,794,011
  tokens).
- `test_safety_panel.py` (23 + 1 local): the 31 incidents grouped by rule, budget kill with computed freeze delay,
  106 pairs folded, policy-derived explanations, context windows resolvable through `/feed`, canary kills with
  evidence and highlights, hostile evidence/rule ids/severities, live status light, read-only.
- `test_stream.py` (32): framing and headers, resume by `Last-Event-ID` and `?from=` without gaps or duplicates,
  filters, bad cursors (400), token header only, paging equals streaming, real uvicorn server for: latency under 2 s,
  torn line held back, late file, heartbeat, reconnect, `run.ending`/`run.ended` with scoring in flight, crashed harness,
  no writes or extra files, no leaked descriptors or threads after disconnect, 429 over the stream cap.
- `test_live_real.py` (4, local): the real `runs/` directory (stream tail, full replay with resume, nothing modified,
  polling cost).
- `tests/integration/test_ui_live_scripted.py` (1, local): a real orchestrator scripted run followed live (checkpoint
  events within 2 s, `/live` sees progress and cost 0.04, end announced, run directory unchanged afterwards).

In total 112 new tests (105 default, 7 local). Commands (from the worktree root, `.venv` interpreter):
`python -m pytest tests/unit/ui_server` (184 passed, 6 deselected) and
`python -m pytest tests/unit/ui_server tests/integration/test_ui_live_scripted.py -m local` (7 passed);
`ruff check ui_server tests/unit/ui_server tests/integration/test_ui_live_scripted.py` is clean.

## Measured (haiku pilot, 37 MB, 14,085 lines)
First `/live` 0.05 s, repeat 0.4 ms; full `from=start` replay of 2,258 visible events 0.24 s; default tail start 18 ms;
`/safety` with 31 incidents and context windows under 50 ms.

## Deviations / notes
- `GET /api/runs/{id}/feed*` and `/api/feed-schema` are additions beyond the brief's `feed-schema` (a paged display-event
  endpoint and a single-event endpoint were needed for incident context links and the Events tab).
- The folded telemetry row is re-sent on the stream (same `id`) on every stall start and end, so a run with 106 pairs
  produces 212 small messages; the client replaces by `id`.
- Out-of-order bound: a line that reaches disk later than a later-stamped line from another file is delivered late (at
  most one poll interval, 0.25 s). Documented; ids and cursors are unaffected.
- `RunLive` and the safety index cache per run in memory (8 runs, LRU). A restart of the UI server rebuilds them in
  well under a second.

## Unresolved
- Resume cursors are byte offsets: if a run directory is replaced by a different run with the same id the server
  restarts that file at 0 (no error); the client may then see duplicate rows. Not expected in practice.
- `pyproject.toml` lists package `ui_server` but not `ui_server.routes`; an installed (non-editable) copy would miss the
  route modules. Predates this phase (U1), not touched here because it is outside this phase's file scope.
- Incident `context` for effect-channel and budget incidents is time-nearest, not exact (flagged `exact: false`).
- The ordering of two events with the same `ts` from different files follows the file name, not write order.
- The `agent.test_run` and `session.init` summarizers are only exercised by synthetic events: the fixture excerpt of
  the agent stream does not contain them.
- Not built (frontend, later): the Live and Safety views, tab-title badge, search, pause/jump-to-now. Notifications and
  sounds remain a non-goal (design section 9).
