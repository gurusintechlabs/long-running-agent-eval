# Internal interfaces (Phases 2–4)

This file pins the data contracts between modules built in Phases 2–4, so they can be built and
tested independently. `docs/spec.md` stays the source of truth for *behaviour*; this file only
fixes names, shapes and signatures. All times are seconds unless a name says otherwise.

## 1. Event files per run (`runs/<run_id>/events/`)

Every line uses the envelope of spec §6.1 (`ts, mono_ns, run_id, source, type, seq, payload`),
written by `telemetry.events.EventWriter`.

| File | source | Written by | Types |
|---|---|---|---|
| `orchestrator.jsonl` | orchestrator | runner | `state`, `turn.start`, `turn.end`, `checkpoint`, `preflight*`, `run.clock`, `run.error`, `cleanup.error`, `user_memory`, `run.resumed` |
| `agent_stream.jsonl` | agent_stream | runner pump | raw `stream.<type>` (unchanged CLI message as payload) **followed by** the parsed events of §2 |
| `otel.jsonl` | otel | OTLP receiver | native names (`claude_code.api_request`, `claude_code.cost.usage`, …), `otel.duplicate` is never written (duplicates are dropped and counted) |
| `guardrail.jsonl` | guardrail | monitor / kill switch | §3 |
| `scorer.jsonl` | scorer | scorer | §4 |

`orchestrator.jsonl` events relied on downstream:
- `run.clock` `{start_epoch, offset_s}` emitted when entering RUNNING. `offset_s` > 0 on resume.
- `checkpoint` `{k, t_s, head_sha, head_tree, dirty, worktree_hash, file_count, pause_ms, cumulative_cost_usd, pip_freeze_hash, final?}`. `t_s` is the run-time offset (includes resume offset). `final` is `"kill"`/`"budget"`/`"interrupt"` for a snapshot taken by the kill switch.
- `state` `{from, to, ...}`; the last one is the terminal state.

Interval boundaries for counters are the envelope `mono_ns` of the `state → RUNNING` event that
follows `run.clock` (interval start) and of each `checkpoint` event.

## 2. Stream parser (`telemetry/stream_parser.py`)

`parse_message(msg: dict) -> list[tuple[str, dict]]` turns one `stream-json` message into parsed
events (type, payload). The runner pump emits each into `agent_stream.jsonl` after the raw event.

| type | payload |
|---|---|
| `session.init` | `{session_id, model, tools, mcp_servers, permissionMode, apiKeySource}` |
| `assistant.text` | `{session_id, text}` (text truncated to 20 000 chars, plus `text_sha256` and `truncated`) |
| `tool.call` | `{session_id, tool_use_id, tool, input}`; any string value in `input` longer than 20 000 chars is truncated, with `input_sha256` of the full canonical JSON and `truncated: true` |
| `tool.result` | `{session_id, tool_use_id, is_error, size}` |
| `session.result` | `{session_id, subtype, is_error, total_cost_usd, num_turns, usage, modelUsage, result_text?}` (`result_text` only when `is_error`, truncated to 2 000) |
| `context.compaction` | `{session_id, trigger, pre_tokens}` from a `system` message with `subtype == "compact_boundary"` |

## 3. Guardrails (`guardrails/`)

`guardrails/policy.py`
- `load_policy(path) -> Policy`; `Policy.sha256` = hash of the file bytes.
- `Policy.bind(work: Path, repo: Path, agent_state: Path, home: Path) -> BoundPolicy` substitutes `{WORK}`, `{REPO}`, `{AGENT_STATE}` and `~`.
- `BoundPolicy.check_tool_call(tool: str, tool_input: dict, cwd: Path) -> list[Violation]` (command channel; Bash `command` text is checked against `forbidden_commands` and every path-like token against `out_of_workspace`; Read/Write/Edit/MultiEdit/NotebookEdit `file_path`/`notebook_path`, Glob/Grep `path`/`pattern` are resolved relative to `cwd`, following `..`, `~`, quotes and symlinks).
- `BoundPolicy.check_effects(workspace: Path, seed_files: dict[str, str] | None) -> list[Violation]` (forbidden_paths globs: a matching file that is new or whose sha256 differs from the seed).
- `Violation(rule_id, severity: "violation"|"warning", action: "log"|"kill", channel: "command"|"effect"|"budget"|"integrity", evidence: str)`.

`guardrail.jsonl` types:
- `guardrail.violation` `{rule_id, severity, action, channel, evidence, stream_seq?}`
- `guardrail.kill` `{rule_id, reason: "policy"|"budget", detect_mono_ns, frozen_mono_ns, freeze_latency_ms}`
- `guardrail.budget` `{cost_usd, tokens, per_run_usd, per_run_tokens}` (on exhaustion)
- `guardrail.telemetry_stalled` `{reason: "lag"|"silence", otel_lag_ms?, silence_s?}` and `guardrail.telemetry_resumed` `{paused_s}`
- `platform.interruption` `{kind: "api_error"|"usage_limit"|"auth"|"clock_gap"|"agent_exit", detail, reset_at?}`
- `guardrail.monitor` `{status: "started"|"stopped", policy_sha256}`

## 4. Scorer output (`scorer.jsonl`)

One scoring pass of checkpoint k writes, in order: `scorer.start {k, pass_id}`, the metric events,
the hazard events, `scorer.done {k, pass_id, duration_s, ok, error?}`. `pass_id` is a uuid4 hex.
Consumers use, for each k, the **last pass that has a `scorer.done` with ok = true**.

- `scorer.metric` `{k, pass_id, name, value, detail}`. `value` is a float or `null`.
  - Core names (all 7 required per checkpoint): `P`, `R`, `D`, `C`, `W`, `X`, `S`.
  - Auxiliary names: `D_delta`, `S_int`, `X_spread`, `tokens_per_commit`, `accepted_commits`
    (cumulative count), `tests_tampered` (0/1), `W_repeat_tool_calls`.
  - `null` needs `detail.reason`. `S`/`S_int` are `null` with reason `no_accepted_commits` when
    the denominator is 0. `X` is `null` only when the judge failed twice.
  - `P.detail.outcomes` and `R.detail.outcomes` hold `{test_nodeid: "passed"|"failed"|"error"|"skipped"}`
    for the hidden and regression suites (R at k compares against these at k-1).
- `scorer.hazard` `{k, pass_id, dimension: "quality"|"context"|"cost"|"safety", rule, t_detected_s, t_attributed_s, evidence}`. At most one per (run, dimension) across all passes of the *same* scoring lineage: when re-scoring checkpoint k, hazards from checkpoints < k are carried as known.
- `judge` raw outputs are cached in `runs/<id>/scorer/judge-cache/<sha256 of input bundle + sample index>.json`.

Times: `t_detected_s` = checkpoint `t_s`; `t_attributed_s` per spec §8.4 / D-9. For a commit, it is
`committer_epoch − run start_epoch`, clamped into `[t_{k-1}, t_k]`. Scripted runs commit with a
fixed date in the past, so their commit hazards clamp to `t_{k-1}`. Safety hazards use the
`guardrail.violation` event `ts` minus the run start epoch.

## 5. Scorer API

```python
# scorer/run_checkpoint.py
score_checkpoint(art: Path, k: int, *, spec: LoadedSpec, scorer_python: Path,
                 judge_runner: JudgeRunner | None = None, final: str | None = None) -> CheckpointScore
# CLI: python -m scorer.run_checkpoint --art runs/<id> --k K [--spec PATH]
# `lrae score <run_id> [--checkpoint K]`, `lrae score --snapshot fixtures/snapshots/known_bad`
# `lrae install-scorer` builds tools/scorer-venv (seed lock + scorer/requirements.txt)
```

The scorer reads only: `snapshots/t{k}/{workspace,meta.json,pip-freeze.txt}`,
`snapshots/t{k-1}` (or the seed), `mirror.git`, `events/*.jsonl`, `manifest.json`, and the spec's
`hidden_tests`, `constraints_file`, seed repo. It writes only `events/scorer.jsonl` and
`scorer/` under the artifact dir. Agent code runs only in subprocesses (I-4).

Judge (`scorer/metrics/x_judge.py`): `JudgeRunner = Callable[[str prompt, str model], str raw_stdout]`.
The default runs the installed `claude` CLI; `scoring.judge_runtime: scripted` selects the
deterministic fake used by tests and scripted pilots (`scorer.metrics.x_judge.FakeJudge`).

## 6. Metrics store (`analysis/ingest.py`)

`ingest(runs_dir: Path, db_path: Path) -> IngestReport` builds the tables of spec §9.1 from scratch
(drop + rebuild in a temp file, then atomic rename). Extra columns beyond §9.1:
- `runs`: `ttfh_s` (null if censored), `event` (1 = hazard, 0 = censored), `cost_usd`, `tokens`.
- `hazards`: unchanged; `counters`: names from `telemetry.counters.interval_counters`.

`telemetry/counters.py`:
```python
interval_counters(events_dir: Path, models_yaml: Path | None = None) -> list[dict]
# one dict per checkpoint k (1-based, in order), each {"k": k, "<name>": value, ...}
# names: tokens_in, tokens_out, tokens_cache_read, tokens_cache_creation, cost_usd, tool_calls,
#        context_fill_max, context_fill_last, compactions, turns, sessions, api_errors, otel_lag_ms_p95
# plus cumulative variants prefixed "cum_" for tokens_*, cost_usd, tool_calls, compactions, turns.
cumulative_cost(otel_events: Path) -> float                       # unchanged signature
cumulative_tokens(otel_events: Path) -> int
```

## 7. Scorer internals (shared by `run_checkpoint.py` and the metric modules)

```python
# scorer/metrics/c_constraints.py
@dataclass(frozen=True)
class ProbeContext:
    snapshot_ws: Path            # fresh temp copy of the snapshot working tree (has .git)
    seed_ws: Path                # pristine seed checkout at seed_commit
    pip_freeze_text: str | None  # snapshots/t{k}/pip-freeze.txt, if recorded
    seed_lock_text: str          # task.seed_requirements_lock contents
@dataclass(frozen=True)
class ProbeResult:
    violated: bool
    evidence: str
PROBES: dict[str, Callable[[ProbeContext, dict], ProbeResult]]   # vendor_unchanged, no_new_dependencies, endpoint_change_has_test
def score_constraints(ctx: ProbeContext, constraints: list[dict]) -> tuple[int, dict]
#   -> (C, {"probes": {constraint_id: {"probe", "violated", "evidence"}}})

# scorer/metrics/w_repeat.py
def repeat_work(repo: Path, seed_sha: str, prev_sha: str, cur_sha: str) -> dict
#   repo = a git working copy or bare repo containing all three commits.
#   -> {"W": float, "lines_added": int, "lines_deleted_own": int, "detail": {...}}; W = 0.0 when lines_added == 0
def repeated_tool_calls(stream_events: Path, start_mono_ns: int, end_mono_ns: int) -> int

# scorer/metrics/s_cost.py
def cost_metrics(*, cum_cost: float, cum_accepted: int, int_cost: float, int_accepted: int,
                 cum_tokens: int) -> dict   # {"S", "S_int", "tokens_per_commit"} (None + reason when denominator 0)

# scorer/metrics/x_judge.py
JudgeRunner = Callable[[str, str], str]          # (prompt, model) -> raw stdout of `claude -p --output-format json`
class ClaudeJudgeRunner: ...                     # installed CLI, tools disabled, scrubbed env, temp cwd
class FakeJudge: ...                             # deterministic; contradictions derived from the bundle hash
def build_bundle(*, task_prompt: str, constraints: list[str], assistant_texts: list[str],
                 commit_messages: list[str], diff: str) -> str
def judge(bundle: str, *, model: str, samples: int, runner: JudgeRunner, cache_dir: Path) -> dict
#   -> {"X": float | None, "X_spread": float | None, "samples": [...], "judge_cost_usd": float, "reason"?: str}

# scorer/hazards.py
@dataclass
class CheckpointView:            # what the hazard rules need for checkpoint k
    k: int; t_s: float; t_prev_s: float
    R: float | None; C: float | None; W: float | None
    S_int: float | None; int_cost: float; int_accepted: int; cum_accepted: int
    first_offending_commit_t_s: dict[str, float | None]   # {"quality": .., "context": ..}
def evaluate(views: list[CheckpointView], *, guardrail_violations: list[dict], run_start_epoch: float,
             thresholds: Thresholds) -> list[dict]
#   views = checkpoints 1..k in order; returns the scorer.hazard payloads (minus pass_id) for every
#   dimension whose FIRST hazard is at or before view k, at most one per dimension.
#   Re-scoring k therefore reproduces the same hazards.
def attribute_commit(repo: Path, commits: list[str], is_bad: Callable[[Path], bool]) -> str | None
#   first commit (oldest first) whose tree is bad; trees are materialised with `git archive` in a temp dir.
```
