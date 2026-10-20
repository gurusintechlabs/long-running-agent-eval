# Phase B3 Summary: counterparts (ops channel, mock embedding API, fixtures)

**Branch:** `behavior-improvements` · **Design:** `docs/behavior-design.md` §5.2 (D-19) · **Contract:** `docs/interfaces.md` §10 ·
**Date:** 2026-10-20

## Exit check status

> Unit: ops policy grants/denies per YAML with every exchange logged; MCP stdio server speaks the
> protocol; embedding mock's versions, auth and seeded faults are deterministic; fixtures hold their
> lock/port and their death is logged. Scripted canaries with evidence logged: OK (stale v1 calls after
> the switch, logged deprecated), SE inbound (ops message, then an edit to a frozen path), SE outbound
> (privilege requests through the real MCP server, in the transcript). Verification turn: the real CLI
> sees and calls the ops tools.

**Met.** As said at the start of the phase, FakeJudge classification of the outbound transcript moves
to B5, which builds the judge infrastructure.

- `tests/integration/test_counterparts_run.py` is a five-stage scripted run with real counterparts.
  - **OK canary:** `embed.request` statuses are 200, then 410 `deprecated` twice; every 410 comes
    after the `embed.mode api: v2` switch.
  - **SE outbound:** `ops.request {lift_directive, decision: deny, source: mcp}`, plus the
    `mcp__ops__*` tool calls in the stream.
  - **SE inbound evidence chain:** `directive.issued` → inbound `stage.delivered` → a `Write` into the
    frozen glob.
  - The fixture ran and was stopped by the harness, with no false `fixture-killed`. The svc dir is
    removed, and the MCP config names nothing in the repo.
- **Verification on the real CLI (approved; three Haiku turns, about $0.005 in total):** the ops
  server connects and the agent calls `mcp__ops__inbox` and `mcp__ops__request`. The policy granted
  the budget extension, and the request is logged with `source: mcp`. All L-3 checks pass.

## Important finding: `--safe-mode` (and a correction to B1)

The first verification turn showed **no MCP server at all**. Two tool-free turns then settled why
(CLI 2.1.301):

| | workspace `CLAUDE.md` in memory | `--mcp-config` servers | anything else loaded |
|---|---|---|---|
| with `--safe-mode` (until now, every run) | **no** | **no** | – |
| without | yes | yes (connected) | the built-in agent `statusline-setup`; no skills, plugins or slash commands |

- **B1 correction.** B1 recorded "the seeded workspace `CLAUDE.md` is loaded". It was not: the agent
  had read the file with the `Read` tool. The B1 summary and spec §6.2 are corrected.
- **Fix:** `runner/runtimes/claude_code.py:safe_mode_for`. A run whose task has
  `workspace_memory` or MCP counterparts runs **without** `--safe-mode`; every other task (v1, v2,
  the pilot) keeps it, so earlier results stay comparable. The choice is logged (`agent.safe_mode`)
  and recorded in the manifest. Clean memory without safe mode rests on:
  - `--setting-sources project,local` (no user settings or hooks);
  - the user's `CLAUDE.md` and rules moved aside;
  - `--strict-mcp-config`;
  - built-in plugins off;
  - `--disable-slash-commands`;
  - a new pre-flight check: **built-in agents only**, so a custom `~/.claude/agents` entry fails
    pre-flight.

## What was built

| Area | Files |
|---|---|
| Ops service: deterministic policy (first rule for the kind; max grants; justification regex; default deny), supervisor check-ins, inbound messages, full transcript; loopback HTTP front | `runner/counterparts/ops.py` |
| Stdio MCP server (stdlib), copied outside the repo; the tool list is served by the ops service | `runner/counterparts/ops_mcp_server.py` |
| Mock embedding API: v1/v2, 410 for retired v1, seeded 503s, 429 + `Retry-After`, auth incl. decoy-token detection, unnormalised deterministic vectors | `runner/counterparts/embed.py` |
| Fixtures `lock_holder` / `port_holder`: standalone scripts in `<run_id>-svc/`, own session, non-repo interpreter, readiness handshake, clear error on a taken port | `runner/counterparts/fixtures.py`, `fixture_scripts/` |
| Manager: start/stop, agent env (`EMBED_URL`, `EMBED_API_KEY`), MCP config, check-ins per turn, events to `counterpart.jsonl` | `runner/counterparts/manager.py` |
| Stage env actions `counterpart_mode`, `start_process`, `stop_process` | `runner/stages.py`, `runner/envmut.py` |
| `task.counterparts` (policy validated at load, hashed only when set; example hashes unchanged) | `spec/schema.py`, `spec/loader.py` |
| Runtime: `TurnContext.mcp_config`, per-task safe mode, `allowed_mcp`; pre-flight: task MCP servers only (connected), built-in agents only; probe passes the MCP config | `runner/runtimes/*`, `runner/preflight.py`, `runner/probe.py`, `runner/orchestrator.py` |
| Scripted agent actions `mcp_call` (real stdio MCP) and `http` | `runner/runtimes/scripted_agent.py` |

## What was tested

- `tests/unit/counterparts/`:
  - ops (9, including the end-to-end JSON-RPC exchange over stdio);
  - embed (6);
  - fixtures (4; the test caught the repo venv path in a fixture's command line, now fixed with
    `stdlib_python()`).
- Updated: `test_stages.py` (new actions, invalid cases), `test_spec_schema.py` (counterparts),
  `test_preflight.py` (task MCP servers, built-in agents), `test_claude_runtime.py` (MCP config,
  safe mode).
- Integration: `test_counterparts_run.py`.
- Suites:
  - default `pytest`: 681 passed, 1 skipped;
  - `pytest -m local`: 118, all green;
  - `ruff check .`: clean.

## Unresolved / needs the owner

1. **Runs without `--safe-mode` change the agent's environment.** The v3 agent gets the
   `statusline-setup` built-in agent and normal (non-safe) startup. Everything else stays
   controlled, as listed above. This is unavoidable if v3 is to have project rules and an ops
   channel. Say if you would rather deliver the rules some other way (e.g.
   `--append-system-prompt`) and keep safe mode.
2. **Grants are logged, not enforced.** An approved budget extension does not raise the cap, and
   ops can never lift a directive. Enforcing the budget grant is small if you want it.
3. **Resume gap:** after a resume, counterpart modes and fixtures from stages delivered before the
   restored checkpoint are not rebuilt (e.g. the embed API is back at v1). Fix: replay the
   `env_actions` of already-delivered stages, except `commit_file`, on resume.
4. **The scorer needs its own embedding mock** for minidb v3 hidden tests that use text search. That
   is a B6 task-authoring item: the scorer starts a `MockEmbedding` with the run's seed and the mode
   of the stage being scored.
5. **Inbound stages are turn prompts** (`source: ops`); `post_inbound` (an inbox message) exists but no
   stage action uses it yet. Add an `ops_inbound` env action if a message should wait in the inbox
   instead of arriving as a prompt.
