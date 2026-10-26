# Phase UH: UI backend hardening (review findings)

Branch `ui-hardening` (from `origin/ui-manager`). Scope: `ui_server/` only, plus tests and `docs/ui-api-control.md`. Nothing in
`runner/ scorer/ telemetry/ guardrails/ spec/ analysis/` was touched; no `claude` was run, no API test, no run launched
(every spawn in the tests goes through a fake spawner; process decoys are sleepers).

"Reproduced" = a test or probe failed (or a probe hung) on the unfixed code before the fix.

## Findings

| # | Finding | Reproduced | Fix | Tests (tests/unit/ui_server/) |
|---|---|---|---|---|
| 1 | Spend gate under-reports (`scoring.security.ai_review` + default `ai_review_runtime: claude_code`) | yes (`test_preview_flags_security_review_spend`, `test_score_refuses_security_review_spend` failed) | `ui_server/spend.py::spend_reasons`, the only predicate; used by `compute_estimate`, `resume_estimate`, `/score`. Audit of every claude path in `runner/` and `scorer/`: agent, X judge (every checkpoint), behaviour judges (follow `judge_runtime`), security AI review (only when `security.enabled and ai_review`); counterparts/exploit tests use no CLI. `/score` now refuses with `judge_spends` for any of them. | `test_uh_spend.py`: every `spec/examples/*.yaml` against a hand rule, 9 synthetic variants, `test_new_runtime_field_must_be_classified` (walks `Spec.model_fields`, fails if a runtime-typed field is not in `CLASSIFIED_RUNTIME_FIELDS`) |
| 2 | `max_spend_usd` is not a maximum | yes by arithmetic (cap 5, per_run 3, 2 runs: nominal 5, worst 6), pinned in `test_worst_case_formula` | `worst_case_usd`: the CLI starts the next run while `spent < cap`, so at most `ceil((cap - spent)/per_run)` (and `<= n`) runs start, each `<= per_run`. `spent` = `runner.cli.experiment_spend` (the CLI's own function). The typed confirmation echoes `max_spend_usd` (worst case); `nominal_cap_usd` and `max_spend_basis` are shown too. At launch a grown worst case is refused (`spec_changed`). Doc updated. | `test_worst_case_formula`, `test_worst_case_uses_spent_from_manifests`, `test_control.py` updated expectations |
| 3 | Harness detection misses macOS styles | yes (a fake `lrae` script runs as `.../Python.app/Contents/MacOS/Python ./probe/lrae run x.yaml`; old matcher said no) | `ui_server/harness_proc.py::parse_argv`: case-insensitive `python*`, `-m runner.cli`, `<..>/lrae` at argv[1] (relative or absolute), `runner/cli.py`, bare `lrae`; understands the global `--repo-root/--claude-home/--home` options and the verb. `-c` never matches. `Control.active()` also scans processes by command line (a terminal run in pre-flight, before any manifest, blocks launches). | `test_uh_proc.py`: matcher table (incl. the real Python.app path), real decoys for `module`, `script` (python-shebang `lrae`), `clipy`; launch refused with no manifest; stop works for each style |
| 4 | Tampered manifest can aim stop/kill at any harness-looking process | yes by construction (old `verify_harness` needed only pid, argv shape and `create_time <= start+5`) | `harness_proc.verify`: numeric `start_epoch` required; argv must name this run (`resume <run_id>`, or `run <spec>` equal to manifest `spec_path` and within `--config/--repeat`); must belong to this repo (`--repo-root`, else cwd inside the repo, else an open file inside the run dir); not younger than the run (+5 s); fail closed without a repo. Else `409 not_a_live_harness`. | `test_unrelated_harness_looking_process_is_never_signalled` (other repo, other spec, other config, no start_epoch, string start_epoch, no spec_path, cwd outside), `test_resume_decoy_must_name_this_run`, `test_the_verified_process_is_signalled_only_with_a_matching_manifest`, `test_verify_fails_closed_without_a_repo` (kill spy asserts no `os.kill` for decoys) |
| 5 | Symlinked `events/` (and other artifacts) followed | yes (`test_symlinked_artifact_answers_like_a_missing_one` failed for events_dir, manifest, review files, mirror dir; `/feed`, `/stream`, `/live`, `/timeline` served the canary or differed) | `ui_server/safefs.py`: paths under a registered runs dir are opened component by component with `O_NOFOLLOW` and `dir_fd` (`open_fd/open_file/stat_file/listdir/read_*`, `no_symlinks_below`). Used by `store.read_json/read_jsonl/open_ro/ingest_status`, `tailer`, `eventlog`, `feed`, `live_state`, `sigcache`, `review_store`, `routes/review`, scorer-log route, `rule_docs` policy read, `gitview.mirror_check`, resume snapshot check, and `timeline` (which hands the dir to `telemetry.counters`: only if the dir has no symlink entry). | `test_uh_symlinks.py`: differential test over every `/api` GET route (enumerated from `app.routes`, with query variants, SSE with `follow=false`): for 8 scenarios (events dir, event files, manifest, scorer dir, scorer log, snapshots, mirror.git, review files) the answer with a symlink to hostile external content equals the answer with the artifact absent, and the canary appears nowhere. `test_safefs_primitives` |
| 6 | YAML alias bomb | yes (`yaml.safe_load` + `json.dumps` of the 12-level fan-out still running after 5 s) | `ui_server/safeyaml.py`: SafeLoader subclass that rejects aliases/merge keys and caps nodes (20k), depth (48), size (256 KiB). Used for validate/save/list/get/duplicate, `_raw_of` on drafts on disk (listed as invalid with the reason), policy parsing, and `load_spec_safe` (the spec and every YAML file it names are pre-checked before `spec.loader.load_spec`, which uses plain `safe_load`) in launch/resume/score/nonce re-checks. | `test_uh_yaml.py`: bomb via validate/save, hostile draft on disk (`GET /api/specs`, `GET /api/specs/x`, duplicate), launch preview, bomb in a referenced `constraints.yaml`; each asserts `< 1 s` and RSS growth `< 150 MB` |
| 7 | Review API 500s on malformed scorer events | yes (`TypeError: unhashable type: 'dict'`, `'int' object is not iterable`) | `review_store`: `k` coerced (int or digit string) else the event is dropped; text/number/evidence fields coerced and bounded; evidence in the dedupe key is JSON-serialised; non-object payloads dropped; `review-items.json`/`review-draft.json` shape-checked; decisions with unknown `decision` ignored. `/api/review/runs` and `/queue` isolate failures per run (`error` / `errors` fields). | `test_uh_review.py` |

### Plausible issues

| Issue | Reproduced | Fix | Tests |
|---|---|---|---|
| `run_git` stalls without output | by reading (blocking `stdout.read`); the test was written after the fix and not run against the old code | `select` loop with an overall deadline, own session, `killpg` on timeout/cap | `test_uh_git.py::test_a_git_that_stalls...`, `..._process_group_is_killed`, `test_slow_dribble...` |
| `info/attributes` `-diff` hides text; alternates | yes by reasoning; `--text` was tried and dropped (it breaks the "Binary files differ" output of real binaries) | `gitview.mirror_check` refuses (with a reason shown in the diff panel) a mirror with symlinks, `objects/info/alternates`, `commondir`, `gitdir`, attributes `-diff`/`binary`, or a `binary` key in config. Diff drivers stay allowed (no external diff/textconv runs). | `test_uh_git.py` (attributes, binary macro + config binary, alternates, symlinked objects, env) |
| Spec TOCTOU | n/a | Kept the post-launch hash compare (+ emergency SIGINT): copying the spec to a private file would change `manifest.spec_path`, break `resume` (reloads `spec_path`) and the relative path resolution, i.e. "reproducible from its spec file alone". Added a second full re-check inside the start lock, immediately before the spawn. Residual window: the CLI's own load. See proposal P1. | `test_edit_between_the_checks_and_the_spawn_is_caught`, existing `spec_changed` tests |
| work_dir/seed_repo/prompt_file not shown | yes | `outside_spec_hash` in the estimate (so it is bound into the nonce) | `test_estimate_names_paths_outside_the_hash`, `test_work_dir_or_seed_repo_change_after_preview_invalidates_the_nonce` |
| `--runs-dir` differs from `<repo>/runs` | yes | all control POSTs answer `409 control_disabled`, `/api/control/state` has `control_enabled` + reason | `test_uh_control.py` |
| `/score` allowlist and error text | yes | `resolve_spec_path` on the manifest's `spec_path` (403), error text no longer includes exception text | `test_score_applies_the_spec_root_allowlist` |
| POST body size | yes | pure-ASGI `BodyLimit`, 1 MiB, also for chunked uploads | `test_uh_http.py` |
| Home paths in `/api/ingest` | yes | `scrub_paths` on the output | `test_ingest_output_is_scrubbed` |
| Headers on 401/403 | yes | `secure_headers` on every response incl. 413 | `test_security_headers_on_every_refusal` |
| `MAX_STREAMS` race | by reading (check before an `await`, increment inside the generator) | slot taken right after the check, released once (generator `finally`, error paths, `weakref.finalize` for a response that never starts) | `test_stream_slots_are_taken_before_the_slow_start`, `test_stream_slot_is_released_after_each_stream` |
| `_atomic_write` overwrites in the race window | yes | `os.link` (fails if the name exists) when `overwrite=False` | `test_atomic_write_never_replaces...` |
| Non-dict `modelUsage` | yes (`AttributeError`) | type checks, non-object lines skipped, unexpected field types skip the event (counted in `invalid_lines`) | `test_uh_live.py` |
| `/api/runs` speed | n/a | `store.read_json/read_jsonl` memoised by (inode, size, mtime_ns), bounded | `test_uh_cache.py` |

### Found while reading, fixed

- A spec's path fields are hashed by content; `task.hidden_tests: /usr` made validate (and launch preview) walk the whole disk
  (reproduced: `PermissionError: /usr/sbin/weakpass_edit`). Now `load_spec_safe` / `spec_store.check` require every file named by
  a spec to be inside the repository (lexically, so symlinks the repo owner placed are fine). `test_uh_paths.py`.
  Consequence: the UI cannot validate/launch a spec that points outside the repo; use the CLI for those.

## What is left / not done

- The TOCTOU between the UI's last check and the CLI's own `load_spec` remains (detected after the fact, run stopped).
- `harness_proc.verify` cannot prove identity against a local attacker who can write both a manifest and craft an argv that
  matches the run; it closes the accidental/tampered-manifest cases only.
- `safefs` keeps a module-level list of registered runs dirs (set by `create_app`).
- Non-run-dir reads that remain path-based: the metrics db (`runs/metrics.sqlite`, checked with `safefs.is_file` then opened by sqlite),
  `analysis.degradation` (opens the db by path), `telemetry.counters.interval_counters` (opens files by name; guarded by a no-symlink
  check of the dir, racy by nature).
- `Control._stop_requested` entries are never removed on the stop path (tiny leak, harmless).
- Resume `max_spend_usd = per_run_usd` ignores what the original run already spent; whether `per_run_usd` is cumulative is a
  runner question.
- The stall test for `run_git` was added after the fix (not run on the old code).

## Proposals that need runner/spec changes (not made)

- P1. `lrae run/resume --expect-spec-hash H`: the CLI refuses to start when its own load hashes differently. Closes the TOCTOU fully
  without copying the spec.
- P2. Manifest should record `harness_argv`, `harness_create_time` (psutil) and `repo_root`: process identity becomes exact instead of inferred.
- P3. `cmd_run`: refuse to start a run unless `spent + per_run <= experiment_usd` (and count in-flight runs). Then `max_spend_usd = min(cap, n*per_run)`
  would be true again and the UI formula could be simplified.
- P4. `spec.loader.load_spec` and `runner.stages.load_stages`, `OpsPolicy.load` etc. should use a no-alias loader and cap `hash_path`
  (size and file count); today only the UI pre-checks.
- P5. `lrae --runs-dir` (and the manifest/active-run logic using it) so the UI's `--runs-dir` can be honoured instead of disabling control.
- P6. `telemetry.counters.interval_counters` should open files with `O_NOFOLLOW` like the UI tailer.

## Verification

See the final report of the session for the suite results (`pytest -n 4 -q -p no:warnings`, and `-m local` for `tests/unit/ui_server` and
`tests/integration/test_ui_*.py`; `ruff check .` clean; `ui_server.__file__` is the worktree copy).
