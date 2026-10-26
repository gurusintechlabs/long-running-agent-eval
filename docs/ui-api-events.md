# UI data API (phase U3): events, transcript, tests, timeline, checkpoint diff

For the frontend. All endpoints are `GET`, JSON, read-only, and behind the same middleware as U1 (Host/Origin check, `X-LRAE-Token` header on every request). `{id}` is a run id (allowlisted, resolved inside `runs/`, else 404). Home and repo paths in responses are shortened to `~` and `<repo>` (as in U1), so a `q` search for a literal home path will not match what is shown.

**Everything the agent produced is untrusted text** (UI-5): transcript text, tool inputs, commit subjects, test ids, evidence. Render with React text nodes only.

Times: `t_s` is run-time seconds (the checkpoint axis; resume offsets applied from `run.clock`), `null` if it cannot be computed. `ts` is the envelope ISO timestamp.

## 1. Cursors (shared by events and transcript)

A cursor is an opaque, server-issued string; never build one from user input and never put one in a path.

| Form | Meaning |
|---|---|
| `agent_stream:123456` | the byte offset where one line of `events/agent_stream.jsonl` starts. As an event id it names that event; as `after` it means "events after this line". |
| `m:agent_stream=123,otel=456,guardrail=0` | merged feed position: next unread offset of each source (missing = 0). Returned as `next` by a multi-source query. |

Rules:
- `next` is always returned, also at end of file. Poll for new events by passing the last `next` as `after` (`eof:true` with an empty page just means "nothing new yet"). Appends to a live file never invalidate cursors.
- An unterminated last line (torn or still being written) is invisible; the cursor stays in front of it and it appears once complete.
- A cursor must be at a line start and not beyond the file end, else 400. A single-source cursor used with another `source` set, or a merged cursor used with one source, is 400.
- Cursors stay valid as long as the file is only appended to (true for run logs). `GET .../events/at?cursor=` fetches exactly one event by its cursor.

## 2. `GET /api/runs/{id}/events`

Query: `source` (comma list of `agent_stream, otel, orchestrator, guardrail, counterpart, env, scorer`; default all), `type` (comma list; exact or glob like `stream.*`, `guardrail.*`), `q` (case-insensitive substring over the raw JSON line, max 200 chars), `after` (cursor), `limit` (default 200, clamped to 1000), `max_chars` (default 2000, 50..20000: strings longer than this are cut).

One source gives `mode:"single"`; more than one gives `mode:"merged"`: a k-way merge by `ts` of the per-file orders, so each file's own order is kept. All files are time-ordered except `otel.jsonl`, whose lines are exported in batches with timestamps up to about 1 s older than lines already written, so the merged feed can be out of order by that much for otel rows.

```json
{
  "run_id": "minidb-v3-pilot-haiku-A-r00-f47fe80e", "mode": "merged",
  "sources": ["agent_stream", "otel", "orchestrator"],
  "events": [
    {"cursor": "agent_stream:7719", "source": "agent_stream", "ts": "2026-10-23T05:38:53.792785Z",
     "t_s": 7.852, "type": "tool.call", "seq": 8, "bytes": 1030, "truncated": false,
     "payload": {"session_id": "3b8a12ef-...", "tool_use_id": "toolu_01NN...", "tool": "mcp__ops__inbox", "input": {}}}
  ],
  "next": "m:agent_stream=8749,otel=0,orchestrator=3953",
  "eof": false, "scan_capped": false, "page_capped": false, "limit": 200, "scanned_bytes": 52114
}
```

Caps and flags:
- Per event: strings longer than `max_chars` are cut with a marker `…[truncated N more chars]` and the event gets `truncated:true`; a payload whose serialised size still exceeds 32 KB is replaced by `{"_truncated": true, "preview": "<first 2000 chars of its JSON>"}`. `bytes` is the size of the original line. A line over 8 MB is returned as `type:"_oversized"` with `payload:null`. A line that is not a JSON object is `type:"_unparsed"` (bad JSON lines inside filters are skipped, not returned).
- Per page: about 4 MB of response (`page_capped:true` and a shorter page; just continue with `next`).
- Per request: at most 16 MB of file is examined (`scan_capped:true`). With a selective `type`/`q` filter a page can come back short or empty with `eof:false`; keep following `next` (it points past the scanned part).

## 3. `GET /api/runs/{id}/events/at?cursor=`

The complete event at a single-source cursor (`full=true` default: strings up to 1,000,000 chars, payload up to 4 MB, else cut with the same markers). Response `{"run_id", "event": {...same shape as above...}}`. 404 if no complete line starts there.

## 4. `GET /api/runs/{id}/events/summary`

Per-source counts from the cached index (a missing file is absent), plus the run clocks.

```json
{"run_id": "...", "sources": {"agent_stream": {"bytes": 10381785, "lines": 6962, "bad_lines": 0,
   "oversized_lines": 0, "first_ts": "2026-10-23T05:38:52.290124Z", "last_ts": "...",
   "counts": {"assistant.text": 463, "tool.call": 596, "tool.result": 596, "stream.assistant": 1527}}},
 "clocks": [{"start_epoch": 1792733925.94, "offset_s": 0.0}]}
```

## 5. `GET /api/runs/{id}/events/locate?source=&seq=|t_s=`

Seek helper (uses the sampled index, one sample per 256 lines, so it reads at most ~512 lines). Give exactly one of `seq` (envelope seq) or `t_s` (first event at or after that run time). Returns `{"found": true, "cursor": "agent_stream:123", "seq": 5, "ts": "...", "t_s": 12.3}` or `{"found": false}`. Use it to jump from a hazard/behaviour `t_s` to a log line (or use `transcript?around_t_s=`).

## 6. `GET /api/runs/{id}/transcript`

A normalised view of `agent_stream.jsonl` built from the parsed events only (`assistant.text`, `tool.call` + `tool.result` merged into one `tool` item by `tool_use_id`, `context.compaction`, `agent.test_run`, `session.init`/`session.result`, `permission.denied`). The raw `stream.*` duplicates are not items.

Query:
- paging: `after` (an item cursor), `limit` (default 100, max 500). Results are in file order.
- filters: `tool` (comma list of exact tool names, e.g. `Bash,Read`), `kind` (comma list of `text, tool, compaction, test_run, session, denied`), `q` (case-insensitive over text, tool name, input and the result tail; the first ~2000 chars of each item are searchable), `errors_only=true`, `turn` (1-based orchestrator turn).
- context window instead of paging: `around=<item or any agent_stream cursor>` or `around_seq=<seq>` or `around_t_s=<run seconds>`, with `before` (default 20) and `after_n` (default 5) items. This is the "20 before, 5 after" view for a guardrail incident. Filters still apply inside the window.
- `max_chars` (default 1500, max 4000) cuts assistant text in the list (`text_truncated:true`).

```json
{
  "run_id": "...", "mode": "page", "anchor": null,
  "items": [
    {"kind": "text", "cursor": "agent_stream:6111", "seq": 6, "ts": "...", "t_s": 7.807, "turn": 1,
     "text": "Following project rule 8, ...", "chars": 76, "text_truncated": false},
    {"kind": "tool", "cursor": "agent_stream:7719", "seq": 8, "ts": "...", "t_s": 7.852, "turn": 1,
     "tool": "Bash", "tool_use_id": "toolu_01L8...", "input_summary": "git status --short && ...",
     "input_truncated": false, "status": "ok", "dur_s": 0.019, "result_size": 4759,
     "result_tail": "...last 600 chars...", "has_result": true, "result_cursor": "agent_stream:8749"},
    {"kind": "compaction", "cursor": "...", "t_s": 9004.5, "trigger": "auto", "pre_tokens": 967292, "turn": 6},
    {"kind": "test_run", "...": "...", "passed": 12, "failed": 3, "errors": 0, "skipped": 0, "raw_summary": "3 failed, 12 passed"}
  ],
  "next": "agent_stream:7719", "eof": false, "total_items": 1151,
  "turns": [{"turn": 1, "start_s": 0.05, "end_s": 712.723, "first": true, "returncode": 0}],
  "tools": [{"tool": "Bash", "count": 490, "errors": 6}],
  "indexed_bytes": 10381785
}
```

Notes: `status` is `ok | error | pending` (no result yet). `input_summary` is the first line of `command`, or `file_path`/`path`/`pattern`, else compact JSON, cut at 200 chars. `turn` comes from `turn.start` events and is `null` when there are none. `total_items` counts the unfiltered items. `tools` is the facet list for the filter chips. Every item's `cursor` and `seq` can be used with `events/at` and with the `stream_seq` of guardrail incidents.

### `GET /api/runs/{id}/transcript/item?cursor=<item cursor>`

Full detail for one item: `{"run_id", "item": {...}, "event": <full tool.call or assistant.text event>, "result_event": <full tool.result event>, "result_text": "<full text from the raw tool result, capped at 200,000 chars>", "result_text_truncated": false}`. 404 when the cursor is not a transcript item.

## 7. `GET /api/runs/{id}/tests?suite=hidden`

Outcome matrix for the heatmap from `test_outcomes` (`suite` is validated against the suites the run has). All numbers come from `analysis.degradation` (`load_matrix`, `flip_events`, `timelines`, `pass_rates`, `status_counts`, `stage_effects`, `window_rates`, `run_summary`, `stage_deliveries`).

Not in the store: `{"run_id", "ingested": false, "has_outcomes": false, "suite", "suites": [], "reason": "this run is not in metrics.sqlite yet; re-ingest to see test outcomes"}` (200). Ingested but no per-test data (old runs): `ingested:true, has_outcomes:false` and empty lists.

```json
{
  "run_id": "...", "ingested": true, "has_outcomes": true, "suite": "hidden", "suites": ["hidden", "regression"],
  "legend": {"p": "passed", "f": "failed", "e": "error", "s": "skipped", "-": "not scored"},
  "points": [{"idx": 0, "t_s": 100.0, "point": "commit", "k": 1, "sha": "c1", "stage": 0}],
  "tests": [{"id": "t/test_t1_a.py::a", "tier": "1", "cells": "ppfp--"}],
  "tests_truncated": false,
  "flips": [{"t_s": 700.0, "test_id": "t/test_t1_a.py::a", "tier": "1", "kind": "regression"}],
  "timelines": [{"test_id": "...", "tier": "1", "first_pass_t": 100.0, "regressions": [700.0],
                 "recoveries": [900.0], "ttfr_s": 600.0, "final_outcome": "failed", "relapsed": false}],
  "pass_rates": [{"t_s": 100.0, "point": "commit", "k": 1, "stage": 0, "passed": 3, "active": 5,
                  "overall": 0.6, "established": null, "tiers": {"1": [3, 3]}, "est_passed": 0, "est_active": 0}],
  "status_counts": [{"t_s": 100.0, "point": "commit", "k": 1, "stage": 0, "passing": 3, "regressed": 0,
                     "not_yet_implemented": 2, "inactive": 1}],
  "stage_effects": [], "window_rates": [], "summary": {"regressions": 7, "relapsing_tests": 1, "...": "..."},
  "checkpoints": [{"k": 1, "t_s": 600.0, "head_sha": "..."}],
  "stages": [{"stage": 0, "t_s": 0.0, "interrupted": 0}]
}
```

`tests[i].cells[j]` is the outcome of test `i` at `points[j]` (heatmap cell). Points are ordered by `(t_s, commits before checkpoints, k)`; `point` is `commit` or `checkpoint`. At most 5000 tests are returned (`tests_truncated`). The server opens the store through `analysis.degradation`, which uses a plain sqlite connection (SELECTs only); a test asserts the file is byte-identical afterwards.

## 8. `GET /api/runs/{id}/timeline`

One payload for the run-detail timeline, built from the log files (so it is current for a run in progress), cached by file signatures. Counters come from the store when the run is ingested, else from `telemetry.counters` over the logs (`source_of_counters: "store" | "logs" | "none"`; the logs path reads the whole `otel.jsonl` once, about 0.15 s cold on the pilot, then cached).

```json
{
  "run_id": "...", "source_of_counters": "store", "end": {"state": "BUDGET_EXHAUSTED", "...": "..."},
  "last_checkpoint_t_s": 17265.1,
  "checkpoints": [{"cursor": "orchestrator:5120", "k": 1, "t_s": 1200.525, "head_sha": "62a1...", "dirty": true,
                   "pause_ms": 100, "final": null, "cumulative_cost_usd": 0.74}],
  "stages": [{"cursor": "orchestrator:...", "stage": 0, "t_s": 0.0, "kind": "feature", "interrupted": false}],
  "markers": [{"t_s": 650.0, "kind": "stage|directive|env", "label": "stage 1"}],
  "states": [{"cursor": "...", "t_s": 0.0, "from": "PENDING", "to": "PREPARING"}],
  "turns": [{"turn": 1, "start_s": 0.05, "end_s": 712.7, "first": true, "returncode": 0}],
  "hazards": [{"dimension": "quality", "rule": "R>0", "k": 2, "t_attributed_s": 1000.0, "t_detected_s": 1000.0,
               "evidence": "regressed"}],
  "behavior": [{"k": 2, "mode": "RH", "dimension": "integrity", "t_s": 900.0, "detector": "tamper",
                "severity": "hazard", "hazard": true, "deterministic": true, "evidence": "..."}],
  "behavior_total": 118,
  "compactions": [{"cursor": "agent_stream:...", "t_s": 9004.5, "trigger": "auto", "pre_tokens": 967292}],
  "guardrail": {
    "status": "clear|warnings|violations|killed",
    "violations": [{"cursor": "guardrail:...", "type": "guardrail.violation", "t_s": 180.1, "rule_id": "other-outside",
                    "severity": "warning", "action": "log", "channel": "command", "evidence": "Edit.file_path -> ...",
                    "stream_seq": 203, "stream_cursor": "agent_stream:512345"}],
    "violations_total": 31,
    "by_rule": [{"rule_id": "other-outside", "count": 28, "severity": "warning", "action": "log", "kills": 0}],
    "kill": {"cursor": "...", "t_s": 17300.1, "rule_id": "budget", "reason": "budget",
             "freeze_latency_ms": 26.7, "detect_to_freeze_ms": 26.7},
    "budget": {"cursor": "...", "t_s": 17300.0, "cost_usd": 15.0, "tokens": 123, "per_run_usd": 15.0, "per_run_tokens": 5000000},
    "telemetry_stalls": {"count": 106, "resumed": 106, "first_t_s": 60.1, "gaps": [{"t_s": 60.2, "paused_s": 0.002}]}
  },
  "series": [{"k": 1, "t_s": 1200.5, "cost_usd": 0.74, "cum_cost_usd": 0.74, "context_fill_max": 0.31,
              "context_fill_last": 0.3, "compactions": 0, "tool_calls": 40, "tokens_in": 1000, "tokens_out": 500}]
}
```

- Cost and context-fill series are per checkpoint (one point per interval); there is no finer series in the logs without reading `otel.jsonl`.
- Link a timeline event to the log: `cursor` (use with `events/at`), or `transcript?around_t_s=<t_s>`; guardrail incidents with a `stream_seq` also carry `stream_cursor` (use with `transcript?around=<stream_cursor>&before=20&after_n=5`). Hazards and behaviour events have no cursor; use `t_s`.
- Incident lists are capped (500 violations, 1000 behaviour rows); `violations_total` and `behavior_total` give the full counts. Evidence strings are cut at 600 chars.
- `telemetry_stalls` is the folded form of the stalled/resumed pairs (one row in the feed).

## 9. `GET /api/runs/{id}/checkpoints/{k}/diff?base=&max_bytes=`

Commits and the unified diff between the checkpoint head (`head_sha` in the orchestrator log) and the previous checkpoint's head; for k=1 the manifest `seed_commit`, else the whole tree (`base_kind: "root"`). `base` (optional) is a full 40-char lowercase hex sha (anything else is 400; a valid sha that is not in the mirror is 404). `max_bytes` caps the diff text (default 400,000; max 2,000,000).

```json
{"run_id": "...", "k": 2, "head": "<sha>", "dirty": true, "base": "<sha>",
 "base_kind": "previous_checkpoint|seed|root|param", "available": true, "reason": null,
 "commits": [{"sha": "<sha>", "parents": ["<sha>"], "date": "2026-10-23T05:41:00+00:00", "author": "agent", "subject": "Add WAL"}],
 "commits_truncated": false,
 "files": [{"path": "minidb/wal.py", "added": 120, "deleted": 4, "binary": false}], "files_truncated": false,
 "diff": "diff --git a/minidb/wal.py b/minidb/wal.py\n...", "diff_truncated": false}
```

`available:false` (200) with a `reason` when the run has no `mirror.git`, the head is not in it, or git failed. Consecutive checkpoints can share a head (`commits: []`, empty diff); `dirty:true` means the checkpoint also had uncommitted files that the mirror does not contain (look at `snapshots/tK` for those; not served in U3). Only the first line of each commit subject is returned (300 chars); binary files appear as `binary:true` and `Binary files differ` in the diff; NULs are replaced.

Git safety: no shell; fixed argument lists; `--git-dir=<run>/mirror.git` (must be a real directory inside the run dir); env reduced to `PATH`, `HOME=/nonexistent`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`; `-c core.hooksPath=/dev/null -c protocol.ext.allow=never -c core.fsmonitor=false -c core.pager=cat`; `--no-pager --no-ext-diff --no-textconv`; stdout read with a byte cap and the process killed when exceeded; 20 s timeout. A test plants a hostile `config`, `info/attributes` and hooks in a mirror and shows nothing runs.

## 10. `GET /api/runs/{id}/checkpoints/{k}/scorer-log?max_bytes=`

`{"run_id", "k", "size", "truncated", "text"}`: the text of `scorer/score-t{k}.log`, the last `max_bytes` (default 200,000; max 2,000,000) when larger (then `text` starts with `…[earlier output cut]`). 404 when absent or when the file resolves outside the run's `scorer/` dir (symlink). `k` is an integer path segment only.

## Status codes

200 ok; 400 bad cursor/filter/sha/source; 404 unknown run/checkpoint/cursor target; 422 FastAPI parameter validation (type or range); 401/403 from the U1 middleware.

## Performance (real 10.4 MB `agent_stream.jsonl`, 6,962 lines, in-process client, M-series Mac)

| Request | Time |
|---|---|
| events summary, cold index of all 7 files (about 27 MB) | 39 ms |
| first page, limit 200 | 11 ms |
| deep page (t_s 9000), limit 200 | 13 ms |
| `q=pytest`, limit 50 | 8 ms |
| `q` with no match (scans all 10.4 MB) | 22 ms |
| merged 7 sources, limit 500 | 32 ms |
| transcript first page (cold item index, 1,151 items) | 32 ms; warm filters 4-5 ms |
| timeline cold / warm | 149 ms / 6 ms |
| checkpoint diff (k=1: 4 commits, 77 KB diff) | about 90 ms |
| walking the whole stream in 35 pages of 200 | 2.3 s, tracemalloc peak 2.9 MB |
