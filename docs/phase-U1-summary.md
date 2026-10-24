# Phase U1: read API and ingest freshness

**Exit check (met):** against the real `runs/`, `GET /api/runs`, `/runs/{id}`, `/runs/{id}/checkpoints` return all 12 manifest runs including the v3 ones, and `/api/ingest/status` reports staleness. `pytest` is green (default suite, plus `tests/integration/test_ui_real_runs.py -m local`).

## Built
- `ui_server/` (FastAPI, local only): `settings`, `safety` (run-id allowlist, containment, path scrubbing), `store` (manifests and orchestrator log on disk, read-only SQLite enrichment, freshness), `app`, `cli` (`lrae ui [--port] [--runs-dir] [--open]`, stdlib-only so `runner/cli.py` can register it).
- Endpoints: `GET /api/health`, `runs`, `experiments`, `runs/{id}`, `runs/{id}/checkpoints`, `ingest/status`; `POST /api/ingest` (runs `lrae ingest` in a scrubbed-env subprocess, single flight).
- Security (UI-1, 2, 4, 5-headers, 7, 8): Host and Origin checks, token on every `/api/*`, CSP and nosniff, no CORS, store opened `mode=ro` + `query_only`, run ids allowlisted, symlinks out of `runs/` refused, home and repo paths scrubbed from responses.
- `ui` optional extra in `pyproject.toml`.

## Finding: the v3 runs were "missing" only because the store was stale
`runs/metrics.sqlite` was last built 2026-10-16; the v3 runs came later. A fresh `lrae ingest` finds all 12. The run list therefore comes from manifests on disk and the store only enriches it. The UI shows `stale` and offers re-ingest.

## Decisions for review
- Token on all `/api/*` including reads (stricter than design UI-2); delivered in the URL fragment.
- `runner/cli.py` imports `ui_server.cli` (stdlib-only) to register `lrae ui`.
- Orchestrator log is read whole per run per list call; fine at today's size (37 KB), revisit with an events index in U3.

## Unresolved
- SSE auth (EventSource cannot send headers): decide in U4 (fetch-stream with header).
- `StarletteDeprecationWarning` for httpx in tests; harmless.
