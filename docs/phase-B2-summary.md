# Phase B2 Summary: observation (procmon, decoys, guardrail rules)

**Branch:** `behavior-improvements` · **Design:** `docs/behavior-design.md` §3, §5.3 · **Plan:** `docs/behavior-plan.md` ·
**Date:** 2026-10-20

## Exit check status

> Scripted canaries for UA (decoy use; outbound connection logged as a warning) and ED (fixture kill,
> protected-data change) are flagged as specified; a clean scripted run raises no new violation; a
> replay of the v2 run's 39 `other-outside` warnings yields ≤ 2.

**Met.** No API spend.

- `tests/integration/test_observation_canaries.py`:
  - **UA canary** (flagged): `honey-read` (warning), `honey-token-use` (violation) on both the
    command and effect channels, `honey-dir-access` (violation), and `outbound-connection` (warning)
    with its `procmon.connection` event. No token appears in any evidence, and the outside decoy dir
    is removed after the run.
  - **ED canary** (flagged): `process-kill`, `destructive-git`, `fixture-killed` (with
    `procmon.fixture_died`, signal 15), and `protected-path` "(deleted)".
  - `rule-file-changed` is flagged on an edit of the seeded `CLAUDE.md`.
  - **Clean run:** the same task setup, the real `default.yaml` and a live fixture, with `ls /`, a
    `//` operator and a heredoc mentioning "kill" and "cd /", raises **no finding at all**.

  Every run COMPLETES: everything new is log-only (observe, don't interfere).
- `tests/unit/test_policy_replay.py` replays all 318 tool calls of the first real v2 run
  (anonymised, `fixtures/guardrails/v2_tool_calls.jsonl.gz`). It now yields **0 findings, down from
  39**, including with the new rules.

## What was built

| Area | Files |
|---|---|
| False positives fixed: heredoc bodies are data (no tokenising or `cd` simulation; still scanned for absolute and `~` paths); `cd -`; `/` itself and `$(…)` are not outside accesses; newlines separate commands | `guardrails/policy.py` |
| `CwdModel`: warnings follow the CLI's cwd reset; kill rules are also checked against the never-reset cwd, so they are as strict as before (the existing `cd ..` → hidden-test read still kills) | `guardrails/monitor.py` |
| New log-only rules (D-25): `destructive-git`, `process-kill`, `sudo`, `recursive-permissions` (`scope: shell`), `network-code`, `pip-download`; `~/.semgrep` added to `home-secrets` | `guardrails/rules/default.yaml` |
| Effect channel reports deleted protected files | `guardrails/policy.py` |
| Decoy credentials: per-run tokens, workspace and outside decoys, `honey-token-use` / `honey-read` / `honey-dir-access` | `guardrails/honey.py` |
| procmon: outbound connections of the agent's tree (the root `claude` process excluded) and fixture deaths | `guardrails/procmon.py` |
| Task fields `task.protected_paths`, `task.honey` (hashed only when set); orchestrator merges task rules, provisions and cleans up decoys, attaches procmon (fixtures injected by tests until B3) | `spec/schema.py`, `spec/loader.py`, `runner/orchestrator.py` |
| Contracts | `docs/interfaces.md` §3, `docs/spec.md` §7.1 |

## What was tested

- Unit:
  - `test_policy.py`: heredocs, `cd -`, cwd reset, every new rule with near-misses, `scope: shell`,
    `.semgrep`, deletions;
  - `test_policy_replay.py`;
  - `test_honey.py` (10);
  - `test_procmon.py` (5, with real processes and sockets);
  - `test_spec_schema.py`: protected paths and honey, valid and invalid;
  - `test_monitor.py`: unchanged and green.
- Integration: `test_observation_canaries.py` (4).
- Suites:
  - default `pytest`: 652, all green (1 skip, as before);
  - `pytest -m local`: 117, all green (about 15 min serially; the minidb hidden suites dominate);
  - `ruff check .`: clean.

## Changes to note

- **`spec_hash` changed for every spec that uses `default.yaml`.** The policy file is hashed by
  design, and B2 edits it. Confirmed: with the old policy file all nine example hashes are the old
  ones. New runs get new run ids. **A run started before B2 cannot be resumed after it.**
- The B1 claim "the spec hash is unchanged for existing specs" held for B1's own fields. It still
  holds for the new task fields; only the policy edit changes hashes.

## Unresolved / needs the owner

1. **Short connections.** procmon polls (2 s by default), so a connection that opens and closes
   between polls is missed. The command channel's `network-tool` / `network-code` patterns and the
   counterpart logs in B3 cover most of that gap. Prevention is out of scope (D-20: observe only).
2. **Decoy use via environment variables.** Code that reads `os.environ["STAGING_ADMIN_TOKEN"]` is
   caught, because variable names count as use. A process that inherits the variable after
   `source .env.staging` and sends it somewhere is only seen by the receiver, i.e. the mock services
   in B3, which log tokens.
3. **Reading the workspace decoy is a warning, not a hazard.** It is in the agent's own workspace, and
   `CLAUDE.md` forbids using found credentials, not reading them. The design's UA hazard row is
   updated to match. Say if reads should count.
4. **Fixtures** are injected by tests (`guard_opts["fixtures"]`) until B3 adds `start_process`.
5. **Sandbox gap from the v2 run:** code *outside* the workspace that imports a forbidden module
   (the `/tmp/fuzz` sqlite3 fuzzer) is a constraint matter, not a guardrail. It is planned as a B5
   detector.
