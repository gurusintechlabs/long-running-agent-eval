# Phase J1 summary: REA wiring, Maven adapters, clean-room similarity (jira-re track)

**Date:** 2026-10-23 · **Branch:** `jira-re` · **Design:** `docs/jira-re-design.md` §7

## Exit check

| # | Check | Result |
|---|---|---|
| 1 | The spec accepts `task.toolchain` and `task.counterparts.rea`; pre-flight verifies the toolchain manifests; the run's MCP config contains `rea` with its env file, so L-3 accepts `mcp__rea__*` | met (unit) |
| 2 | The agent's own suite reruns in Maven mode, read from surefire XML | met (unit, fake `mvn` driven through the seed's real `build.sh`) |
| 3 | The stream parser recognises Maven's test summary | met (unit) |
| 4 | Java constraint probes: offline-repository dependencies, pinned pom properties, every class tested, nothing under `.decompiled/` tracked | met (unit) |
| 5 | Copy similarity per checkpoint against the scorer's own decompilation | met (unit, fake decompiler); wired into `run_checkpoint` |
| 6 | `pytest` and `pytest -m local` green | met: `pytest` exit 0 (one skip); `pytest -m local` 204 passed in 1 h 18 min (run on AC power under `caffeinate`; an earlier attempt was discarded because the laptop slept mid-run) |

No real agent run and no API spend. The real REA, Vineflower and Maven binaries have not been
exercised by these tests: the toolchain is not installed on this machine yet.

## What was built

**REA counterpart (extends D-19, approved by the owner 2026-10-23).**
- `task.counterparts.rea {command, args, env_file}` (`spec/schema.py`).
- `runner/counterparts/manager.py` registers it in the run's `mcp.json` next to `ops`. `~` expands to
  the real home, the env file is `KEY=VALUE` lines, and `rea.configured` is logged to
  `counterpart.jsonl`.
- The harness does not implement REA. The CLI starts it per session, and its calls and full results are
  in `agent_stream.jsonl` like any tool's.
- `_start_counterparts` also starts when only `rea` is configured, which turns safe mode off through the
  existing `safe_mode_for`. Pre-flight L-3 allows it through the existing `allowed_mcp`.

**Toolchain pin.**
- `task.toolchain {dir, manifest_sha256, m2_manifest_sha256}`.
- `preflight.check_toolchain` (J-1 checks) fails a run whose `MANIFEST.txt` or `m2.manifest` differs
  from the pinned hash. Unpinned hashes are not checked.

**Spec hash compatibility.** Unset J1 fields are left out of the hash: `toolchain`, `counterparts.rea`,
the default `agent_suite_runner` and the default `clean_room`. All 13 example specs keep their exact
pre-J1 hashes (checked before and after), so existing run ids and re-scoring are unaffected.

**Maven agent suite** (`scoring.behavior.agent_suite_runner: maven`, needs `task.toolchain`).
- `scorer/behavior/agent_suite.py` runs `sh build.sh test` on a temp copy (without `target/` or `.m2/`),
  in a scrubbed env with `LRAE_RE_TOOLS` pointing at the toolchain.
- It parses `target/surefire-reports/TEST-*.xml` into `Class#method` outcomes.
- A compile failure with no reports is `build_failed`, which is "unknown", like a timeout, and never
  "0 failing".
- The cache key includes the runner. The pytest path is byte-identical to before.

**Stream parser.** `parse_test_summary` tries pytest first, then Maven surefire:
- it uses the last `Results:` total;
- if the output was cut before that, it sums the per-class lines after the last `T E S T S` banner;
- Maven events carry `runner: maven`, and pytest events are unchanged.

**Java constraint probes** (`scorer/metrics/c_constraints.py`, file-only):
- `pom_pinned`;
- `maven_deps_from_repo`: checks against `m2.manifest`, including BOM-managed dependencies with no
  version. With no manifest, the result is "not checked".
- `java_class_has_test`;
- `untracked_path`: reads the snapshot's git index; no agent code runs.

**Clean-room similarity** (`scorer/clean_room.py`, `scoring.clean_room`, metrics `lrae.cr.structural`
and `lrae.cr.lexical`).
- **Reference:** the scorer decompiles the seed's jar once per jar SHA (Vineflower or CFR from the
  toolchain), cached in `runs/<id>/scorer/clean-room-ref/`.
- **Comparison:** Java token k-grams are winnowed into fingerprints. Containment is the share of the
  rewrite's fingerprints found in the reference. Seed-skeleton fingerprints are excluded.
- **Detail:** the ten most similar files are listed.
- **Measured on the test snippets at the default k=25, window 4:**

  | Rewrite | structural | lexical |
  |---|---|---|
  | verbatim copy | 1.0 | 1.0 |
  | renamed and reformatted copy | 1.0 | 0.0 |
  | independent rewrite of the same behaviour | 0.02 | 0.0 |

- No hazard threshold; a pilot calibrates one.

**jira-re task updates.**
- The spec enables the toolchain, REA, the Maven suite (900 s limit) and clean-room scoring. Budget
  $200 (owner).
- `constraints.yaml` uses the four Java probes plus `vendor_unchanged`.
- `tests/unit/test_jira_re_fixtures.py` guards:
  - the spec, stages, seed and constraints (C = 0 on the seed);
  - target resolution;
  - the priming pom;
  - under `-m local`, the hidden suite on a javac-compiled synthetic plugin.

## Tests added

- `tests/unit/test_spec_schema.py`: hash invariance, loading and rejection of J1 fields.
- `tests/unit/counterparts/test_rea.py`: env file, MCP config alone and next to ops, failures.
- `tests/unit/test_preflight.py`: toolchain manifests.
- `tests/unit/test_stream_parser.py`: surefire summaries.
- `tests/unit/behavior/test_agent_suite_maven.py`: XML parsing, outcomes, build failure, no tests,
  timeout, scrubbed env, cache key.
- `tests/unit/scorer/test_c_constraints_java.py`: the four probes.
- `tests/unit/scorer/test_clean_room.py`: tokens, the three similarity cases, background, archive
  outputs, end to end with a fake decompiler and caching, failures.
- `tests/unit/test_jira_re_fixtures.py`.
- One existing test updated because its subject grew: `test_probe_registry_names` pins the probe
  registry, which now has the four Java probes.

## Unresolved, and proposals

1. **Not exercised against real binaries:** REA's MCP server, Vineflower's output layout on a real jar
   (the collector reads both directories and archives), and the AMPS build under the read-only tail
   repository. The first real check is `install_re_tools.sh`, then `prime_maven_repo.py`; a
   scripted-runtime run of jira-re comes after that.
2. **`maven_deps_from_repo` reads its manifest path from `constraints.yaml`** (`~/lrae-tools/re/...`).
   If `LRAE_RE_TOOLS` is overridden, that path must be edited too. Proposal: let probes read
   `task.toolchain.dir`.
3. **D(t) and security scoring are still Python-only.** jira-re leaves security off; D(t) will report no
   Python findings. Proposal: Java semgrep rulesets in a later phase.
4. **The R(t) seed-regression check runs the seed's own tests with pytest.** A Java seed has none, so
   R(t) carries no signal for jira-re. P(t) (the hidden suite) and the Maven own-suite rerun do.
5. **Two-role mode (owner decision: separate analyst and implementer)** is not built. It needs separate
   workspaces, sessions and MCP configs per role. Proposed as **J2** (`docs/jira-re-design.md` §7.5).
6. **Proposed spec decision amendment (D-19):** counterparts may include external stdio MCP servers the
   harness registers but does not implement (REA). Approved in conversation; to be written into
   `docs/spec.md`.
7. **Decision-number collision (found merging main, 2026-10-26).** "D-19" in this track means the behaviour
   track's counterparts decision (`docs/behavior-design.md` §10, still a proposal). `docs/spec.md` on main
   has since confirmed D-19 as the local management UI server, and D-20 as Node as a UI build dependency.
   Proposal: give the counterparts decision, and its J1 extension to external MCP servers, a new number
   (next free in `docs/spec.md`: D-28). Not renumbered here: spec decisions change only with owner
   approval.
