# Phase U3 (data half): events, transcript, tests, timeline, checkpoint diff

Scope: the backend API for the U3 views. The React views are built separately from `docs/ui-api-events.md`.

## Built
- `ui_server/eventlog.py`: seek-by-offset reader, cursors (`src:off`, merged `m:src=off,...`), per-file index (counts by type, one offset sample per 256 lines, run clocks) cached in memory and extended incrementally while a file grows; per-event and per-page size caps; k-way merged feed; torn last line invisible; oversized lines (over 8 MB) reported not parsed; `locate` by seq or run time.
- `ui_server/transcript.py`: normalised transcript from the parsed events (call and result merged, pairing by `tool_use_id`, turns from `turn.start/end`), incremental in-memory item index, filters (tool, kind, text, errors, turn), around-a-cursor/seq/time windows, full item detail including the raw result text.
- `ui_server/timeline.py`: one timeline payload (checkpoints, stages, markers, states, turns, hazards, behaviour, guardrail incidents with kill/budget/stall folding, compactions, per-checkpoint cost and context series), reusing `analysis.ingest` helpers; cached by file signatures (`ui_server/sigcache.py`).
- `ui_server/gitview.py`: safe read-only git for `mirror.git`.
- Routes (auto-discovered): `routes/events.py`, `transcript.py`, `run_tests.py` (reuses `analysis.degradation`), `timeline.py`, `checkpoint_git.py`.
- Docs: `docs/ui-api-events.md`. No existing file was edited (no change to `store.py`, `app.py`, `deps.py`).

## Tested
- `tests/unit/ui_server/test_u3_*.py` (+ `u3_synth.py` helper): 84 new tests, `tests/unit/ui_server` total 163 passed. Security cases each have a test: cursor grammar and path-traversal attempts, mid-line and past-EOF cursors, unknown or repeated sources, symlinked event file/mirror/scorer log not followed, run-id allowlist, token required, base sha validation (`HEAD`, `--output=...`, uppercase, short, `;id`), git run without shell with a scrubbed env and the safety flags, a hostile mirror (`diff.external`, `core.fsmonitor`, `core.pager`, `textconv`, attributes, hooks) that must not execute, binary and ANSI/control characters, size caps (limit, event payload, page, scan, diff, scorer log), no file in the run dir or the store changes (snapshot before/after), `ingested:false` payload.
- `tests/integration/test_ui_u3_real_runs.py` (`-m local`, `LRAE_REAL_RUNS`, default the main checkout's `runs/`; read-only): 8 passed against the haiku pilot. Includes the U3 exit-check pieces: each guardrail violation (31) resolves to a stream line and a transcript window; 106 stall/resume pairs folded; kill with freeze delay; heatmap flips equal `analysis.degradation.flip_events` (store built in a temp dir from a symlink, the real store is not touched); memory bound while paging the whole stream.
- Commands: `.venv/bin/python -m pytest tests/unit/ui_server` (163 passed) and `.venv/bin/python -m pytest tests/integration/test_ui_u3_real_runs.py -m local` (8 passed). `ruff check` clean on the new files.
- Performance on the real 10.4 MB stream: table at the end of `docs/ui-api-events.md` (page 11 ms, full-file search 22 ms, whole stream in 35 pages 2.3 s with a 2.9 MB tracemalloc peak).

## Deviations and decisions to review
- **Merged feed order**: ordered by `ts` over each file's own order; `otel.jsonl` is not time-ordered (batched, up to about 1 s back), so merged otel rows can be out of order by that much. Not corrected, to keep the cursor stateless.
- `analysis.degradation` opens the store with a plain `sqlite3.connect` (not `mode=ro`), so `/tests` does not use the U1 `query_only` connection for those calls. It only SELECTs; the test checks the store file is byte-identical afterwards. Changing `degradation._connect` to read-only would close the gap but edits an existing module.
- Home/repo paths are scrubbed from event, transcript and timeline responses (as U1 does for the run detail). This changes displayed evidence text slightly and means a `q` search for a literal home path does not match what is shown.
- The timeline reads `orchestrator.jsonl`, `scorer.jsonl` (selected types only) and `guardrail.jsonl` per request (cached by file signature), not the store, so it works for non-ingested and live runs; counters come from the store when ingested.
- Search `q` matches the raw JSON line (JSON-escaped text such as `\n`), and the transcript search covers only the first ~2000 chars per item.

## Unresolved
- The diff covers `mirror.git` commits only. Checkpoints with `dirty: true` also have uncommitted files in `snapshots/tK`, which are not served.
- Cost/context series are per checkpoint; a finer series would need a pass over `otel.jsonl` (a per-request index) if the frontend wants one.
- Live tailing (SSE) is U4; these cursors are designed for it (`next` after the last line, torn lines hidden) but no SSE route exists yet.
- The in-memory caches are per process, bounded by file count (64 event indexes, 16 transcript indexes, 64 memo entries); the transcript index keeps up to ~4 KB of text per item, so a very large run could use tens of MB.
