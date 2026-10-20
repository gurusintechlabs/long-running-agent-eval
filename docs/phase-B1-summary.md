# Phase B1 Summary: spec, stages and event model (behaviour track)

**Branch:** `behavior-improvements` · **Design:** `docs/behavior-design.md` · **Plan:** `docs/behavior-plan.md` ·
**Date:** 2026-10-19

## Exit check status

> A scripted staged run with a directive, an environment stage and an inbound stage delivers them in
> order with all events logged; `spec_hash` changes when any new input changes; `pytest` and
> `-m local` green.

**Met**, except the API verification turn, which was not run. It needs approval (see Unresolved).

- `tests/integration/test_staged_run.py::test_behaviour_stage_kinds_env_changes_and_directives`
  runs five stages:
  - stage 0, feature (product owner);
  - stage 1, directive (freeze until stage 3);
  - stage 2, environment (a `commit_file` by platform-bot);
  - stage 3, inbound (ops);
  - stage 4, release (STATUS block required).

  The run uses a seeded `CLAUDE.md` (D-15a) and task deny rules. The test checks:
  - delivery order, kinds and sources;
  - the `From:` header, via `turn.start.prompt_sha256` = `stage.delivered.message_sha256`;
  - the issued/lifted order of the directive;
  - the env commit, made before its stage was delivered, with its author and content in the final
    snapshot;
  - the seeded rules in the workspace;
  - the deny rules in `harness-settings.json`.
- `spec_hash`:
  - covers `workspace_memory`, `permissions.deny` and env-action source files (unit tests);
  - is **unchanged for all nine existing example specs**, checked before and after the change, so
    existing run ids and resumes are unaffected.

## Pre-B1 fixes (found in the v2 run logs)

1. **Account identifier leak.** CLI 2.1.301 adds `user.account_id` to every OTel record, and the
   receiver did not redact it. Redaction now covers the whole `user.*` and `organization.*` attribute
   namespaces (`telemetry/events.py:is_sensitive_key`), so a future identifier cannot slip through.
   Five local run dirs written before the fix still contain the id (see Unresolved).
2. **`AGENTS.md` as memory.** Two built-in plugins (`cc-plugin-agents-md`,
   `cc-plugin-plugin-authoring`) load even under `--safe-mode`. The L-3 init check exempts
   built-ins on purpose: they are pinned by the CLI version. But `agents-md` loads `AGENTS.md`
   files, which the clean-memory checks did not look for. `AGENTS.md` and `AGENTS.override.md`
   now count as memory files in L-1 (ancestors) and L-3 (seed). No `AGENTS.md` exists above the
   work dir today, so no past run was affected. spec §6.2 notes the 2.1.301 `init` changes.

## What was built

| Area | Files |
|---|---|
| Stage fields (D-18a): `kind` (+ `directive`, `environment`, `incident`, `inbound`, `release`), `source` with `From:` header, `surface`, `directives`, `env_actions`, `status_block` | `runner/stages.py` |
| Environment mutator: `commit_file` as a reserved harness identity (`<name>@harness.lrae.local`), pathspec commit leaving the agent's staged/unstaged work alone, hooks disabled (`core.hooksPath=/dev/null`, `--no-verify`), refuses symlinks and paths outside the workspace, reports an overwritten local edit | `runner/envmut.py` |
| Delivery: env actions under the snapshot lock → `env.jsonl`; `stage.delivered` with source, message hash, status block; `directive.issued` / `directive.lifted`; `turn.start.prompt_sha256` | `runner/orchestrator.py` |
| D-15a: `task.workspace_memory`; the seed may carry exactly that `CLAUDE.md` at its root | `spec/schema.py`, `spec/loader.py`, `runner/memory.py`, `runner/workdir.py` |
| Task deny rules `task.permissions.deny` → `harness-settings.json` | `spec/schema.py`, `runner/orchestrator.py` |
| `permission.denied` events from the result's `permission_denials` | `telemetry/stream_parser.py` |
| Harness commits excluded from agent work: accepted commits, per-commit scoring, W(t) own lines, X(t) commit messages | `scorer/metrics/r_regression.py`, `scorer/metrics/w_repeat.py`, `scorer/run_checkpoint.py` |
| Contracts | `docs/interfaces.md` §9.1 |

## What was tested

Tests were written first and confirmed failing, then made to pass:
- `tests/unit/test_stages.py`: rich fields, headers, directive lifecycle, 16 invalid cases, hash
  coverage of env sources;
- `tests/unit/test_envmut.py`: pathspec commit, clobber report, new dirs, agent hooks never run
  (both `.git/hooks` and `core.hooksPath`), symlink refusal;
- `tests/unit/test_memory.py`: D-15a cases, `AGENTS.md`;
- `tests/unit/test_spec_schema.py`: workspace memory, deny rules;
- `tests/unit/test_stream_parser.py`: denials;
- `tests/unit/scorer/test_harness_commits.py`;
- `tests/unit/test_events.py`, `tests/unit/test_otlp_receiver.py`: namespace redaction;
- `tests/integration/test_staged_run.py`: the exit check, plus "an undeclared seed `CLAUDE.md` still
  fails the run".

Suite results:
- default `pytest`: 580 selected, all green;
- `pytest -m local`: 113, all green (about 5 min);
- `ruff check .`: clean.

`-m slow` was not run for this phase.

## Unresolved / needs the owner

1. **Verification turn (needs approval, ≈ $1, Haiku or one short Opus turn).** Not run. It would
   confirm three things on CLI 2.1.301:
   - that a deny rule fires under `--dangerously-skip-permissions` (bypass mode);
   - the real shape of a non-empty `permission_denials` entry, and of an OTel `tool_decision` with
     `decision: reject`;
   - that a workspace `CLAUDE.md` is loaded as project memory while user memory stays excluded.

   The parser accepts the documented SDK shape (`tool_name`, `tool_use_id`, `tool_input`) until
   then.
2. **Old run logs with the account id:** `runs/minidb-v2-early-A-r00-338286d0`,
   `runs/minidb-v2-smoke-A-r00-a4f4d32a`, `runs/stage-handoff-smoke-A-r00-6bc01ce5` and two
   `runs/_failed/…-preflight*` dirs. They are local and gitignored. Scrubbing means rewriting
   append-only logs, so it is the owner's call.
3. **Optional built-in plugin disabling.** Setting `enabledPlugins: {"cc-plugin-agents-md@builtin":
   false, …}` in the harness settings may switch the built-ins off entirely. It can be checked in
   the same verification turn, through the `init` message's `plugins` field.
4. **Task system prompt** (`--append-system-prompt`, v3 design §5) is not built. It waits on open
   question 3 in `docs/minidb-v3-design.md`.
5. **W(t) denominator:** lines added by a harness commit in an interval still count in that
   interval's "lines added". A harness commit is a single doc file, so the effect is small; it is
   noted, not fixed.
6. **Directive events on resume:** stages after the restored checkpoint are delivered again, so
   their directive events can appear twice in `orchestrator.jsonl`. Consumers must key on
   directive `id` (B5 detectors will).
