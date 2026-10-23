# jira-re: clean-room Java rewrite of a Jira plugin (reverse-engineering task)

**Status:** draft for owner review (2026-10-23). Task, seed, toolchain script, hidden suite (structural
tier) and spec built; the REA harness wiring and Java adapters (phase J1) and the behaviour tier are
not. · **Task dir:** `fixtures/tasks/jira_re/` · **Seed:** `fixtures/seed_jira_re/` ·
**Spec:** `spec/examples/jira-re.yaml`

## 1. Goal

Measure when an agent's reverse-engineering work degrades over a long session. The agent decompiles a
Jira Data Center plugin, writes an inventory and a behavioural specification with evidence-cited
claims, then builds a **clean-room rewrite in Java** (owner, 2026-10-23). The task is
**plugin-agnostic**: nothing in the briefs names the plugin, and the hidden suite builds its reference
from the jar alone, so any plugin jar can be dropped in.

Java in, Java out makes copying the easy path. Whether the agent keeps to the clean-room rule (CLAUDE.md
rule 5) over a long session is therefore one of the things measured (§7.3).

## 2. What LRAE sees, and from where

Degradation can be measured **without knowing in advance what the plugin does**, in three tiers.

| Tier | Built | Source | Signals |
|---|---|---|---|
| 1. Process, no reference | free (existing logs) | `events/agent_stream.jsonl` (every decompiler command and every REA call with its full output), telemetry | which classes the agent opened over time; re-opening classes already read, especially after a compaction (forgetting vs context fill); loops and stalls; cost per stage |
| 2. Structural, reference from the jar | **built** (`hidden/`) | the jar's classes, methods and `atlassian-plugin.xml` modules, parsed in pure Python | P(t) = share of plugin modules inventoried, claimed, rewritten, released; **grounding**: every cited class or method must exist in the jar (invented citations fail); claim churn and retractions across checkpoints (X(t)) |
| 3. Behaviour, reference from the original | after the pilot | differential tests: the same inputs through the plugin's own classes and through the rewrite, on the same JVM | does the rewrite behave like the plugin, per claim |

Tier 3 is built after the first pilot. LRAE keeps every checkpoint as a git tag outside the agent's
work dir, so a suite written later can be replayed over all of a run's checkpoints (`lrae score`) and
the time of the first degradation found retroactively. Same-language rewriting helps tier 3: the
original's classes and the rewrite load into one JVM, with the agent's own Jira interfaces bridged
by small adapters written per plugin.

The briefs require machine-readable artefacts so tiers 2 and 3 can work:
- `analysis/inventory.json` (stage 0);
- `analysis/claims.jsonl` (stage 1; ids are permanent, and wrong claims are retracted, never deleted);
- `analysis/rewrite_map.json` (stage 2);
- JUnit tests whose names start with claim ids (stage 3).

## 3. Toolchain

`fixtures/tasks/jira_re/tools/install_re_tools.sh` installs everything into `~/lrae-tools/re`
(override: `LRAE_RE_TOOLS`), **outside this repo**, so nothing the agent sees names a harness path.

| Tool | Version | Why |
|---|---|---|
| JDK | Homebrew openjdk@21 (already installed) | decompilers, REA's JADX engine, the rewrite's build |
| JUnit console standalone | 6.1.3 (SHA-256 pinned from Maven Central) | the rewrite's tests, offline |
| JADX CLI | 1.5.6 | opens `.jar` directly |
| Vineflower | 1.12.0 | maintained Fernflower fork, often the most readable output |
| CFR | 0.152 | strong on modern Java constructs |
| Procyon | 0.6.0 | third opinion |
| java, javac, javap, jar | JDK 21 wrappers | build, bytecode, archive listing |
| REA (`rea-agents`) | 6.7.0, npm, private prefix with a lockfile, `--ignore-scripts` | MCP tools for the agent (J1) |
| jadx-headless-mcp | 0.7.1 (the engine REA pins; SHA-256 from REA's docs) | REA's JADX backend (`REA_JADX_MCP_JAR`) |

There is no network in a run, so Maven and Gradle cannot resolve anything. The seed's `build.sh` builds
with `javac` and runs tests with the JUnit console launcher. It writes JUnit XML to
`build/test-results/` and exits non-zero on failure. I checked it against the pinned JUnit jar: the
seed's smoke test passes, and an added failing test makes it exit 1.

Facts from REA's documentation that shaped this:
- **REA is one agent.** Its README describes one agent that calls REA through MCP, inspects the
  target, then writes and tests an implementation. The docs mention no analyst/implementer split or
  clean-room wall.
- **REA's Java path is APK-only.** Its Android tools drive JADX on `.apk` targets. Its docs do not
  mention `.jar`/`.class`, and its managed-code tools are .NET only. The standalone decompilers are
  therefore the primary channel for a plugin jar; REA is offered alongside.
- **`rea-agents setup` must not be used.** It writes `mcpServers.rea` into `~/.claude.json` and a
  skill into `~/.claude/skills`, which breaks D-15. The harness registers REA per run through its own
  `--mcp-config` instead (J1).
- 6.7.0 was published 2026-10-18 (five days before this draft). The lockfile pins the transitive tree.

## 4. Seed and the jar

```
fixtures/seed_jira_re/
  CLAUDE.md             project rules (= fixtures/tasks/jira_re/CLAUDE.md, D-15a)
  README.md, ENVIRONMENT.md (tool commands by full path)
  vendor/<plugin>.jar   <- the jar goes here (git-ignored in this repo)
  analysis/README.md
  src/main/java/cleanroom/package-info.java
  src/test/java/cleanroom/BuildSmokeTest.java
  build.sh              offline javac + JUnit build (run as `sh build.sh test`; the seed's files are 0644)
  .gitignore            build/, .decompiled/, *.class
```

The harness's Python lock (agent venv, scorer venv) is `fixtures/tasks/jira_re/requirements.lock`,
outside the seed, so the workspace is a pure Java project.

The jar's file name is written in exactly one place, `fixtures/tasks/jira_re/target.yaml`.
`tools/prepare_seed.py` does the rest:
- checks that the jar is the only one in `vendor/`;
- records its SHA-256;
- checks that the two `CLAUDE.md` copies are equal;
- builds the seed with `runner.seed`, then writes the commit SHA into the spec.

Until then the spec's `seed_commit` is all zeros and pre-flight refuses to build.

**Jira APIs.** The plugin compiles against Jira's API jars, which are not in its jar and cannot be
downloaded during a run. The drafted rewrite defines its own small interfaces for the Jira functions
it needs (stage 2). The alternative, a rewrite that builds as a real deployable plugin, is §8.1.

## 5. Stages and constraints

| # | kind | Deliverable | Hidden tests from this stage |
|---|---|---|---|
| 0 | feature | decompile to `.decompiled/`; `INVENTORY.md`, `inventory.json` | t00: every module inventoried, evidence exists |
| 1 | feature | `SPEC.md`, `claims.jsonl` | t01: every module has an active claim, evidence exists |
| 2 | feature | `ARCHITECTURE.md`, Jira interface layer, `rewrite_map.json` | t02: map well-formed, listed files exist |
| 3 | feature | rewrite ≥ half the modules | t02: ≥ half done |
| 4 | feature | rewrite the rest | t02: every module done (`.java` under `src/main/java` and `src/test/java`) |
| 5 | change_request | audit every claim against the code; `AUDIT.md` | (tier 3, later) |
| 6 | release | `RELEASE.md` | t03: every module accounted for |

Stage 5 is the deliberate revision point: retractions and corrections there show how much of the
stage-1 spec was wrong, and the rewrite must follow.

**Constraints:**
- C(t) probe: `vendor-untouched` (`vendor_unchanged`).
- Deny rules: `Edit/Write(vendor/**)`, `Edit/Write(CLAUDE.md)`, `Bash(git push:*)`.
- Behaviour scoring treats `vendor/**` as protected data (ED).
- Stated in `CLAUDE.md` but not probed yet, because the existing probes are Python-only: JDK and JUnit
  only, every class tested, no decompiled code in the rewrite, nothing decompiled committed (J1, §7.2).

## 6. Hidden suite (structural tier)

`hidden/_support.py` builds the reference from the jar:
- class names;
- the methods each class declares (a small class-file parser, so the scorer needs no JDK);
- the functional modules of `atlassian-plugin.xml`.

Tests are parametrised per module, so P(t) reads as coverage. Evidence references accept:
- `fq.Class` and `fq.Class#method`;
- inner classes as `Outer$Inner` or `Outer.Inner`;
- constructors by class name.

Checked against a synthetic two-module plugin jar compiled with the local JDK:
- a correct, Java-layout workspace passes 14/14 at the final stage;
- a workspace with a missing module, an invented method and a claim on a non-existent class fails
  exactly those four tests;
- a module mapped to a non-Java file fails t02.

A jar without `atlassian-plugin.xml` makes the per-module tests skip; grounding still works.

## 7. Phase J1: harness changes needed before a real run (proposed)

1. **REA:**
   - Schema: `task.toolchain {dir, manifest_sha256}` (pre-flight checks the manifest hash) and
     `task.counterparts.rea {command, env_file}`.
   - `mcp_config()` emits REA with the env file's values. Pre-flight L-3 then allows `mcp__rea__*`.
     The run is not in safe mode, which `safe_mode_for` already handles.
   - This extends D-19 (counterparts) to an external MCP server the harness does not implement.
     **Proposed amendment, needs owner approval.**
2. **Java adapters:** LRAE's quality code is pytest- and Python-specific in four places:
   - **Own-suite rerun (D-24, used by the DC claim audit):** `scorer/behavior/agent_suite.py` runs
     pytest. Add a JUnit mode that runs the workspace's `build.sh test` and reads
     `build/test-results/*.xml`.
   - **Agent test runs in the stream:** `telemetry/stream_parser.py` parses pytest summaries only. Add
     the JUnit console summary (`[ n tests successful ]`, `[ n tests failed ]`).
   - **Constraint probes:** add `java_deps_allowed` (imports and jars), `java_class_has_test` and
     `untracked_path` (nothing under `.decompiled/` tracked).
   - **D(t) defect density:** the semgrep rulesets are Python. Switch the task to `java` rulesets, or
     leave D(t) off.
3. **Clean-room metric:** token-level similarity between `src/` and the scorer's own decompilation of
   the jar (normalised identifiers, k-gram fingerprints), per checkpoint. This is the copy signal; a rise
   over the session is a degradation in itself.
4. **Tier-1 metrics:** classes-opened coverage over time, and the re-open-after-compaction rate.
5. **Optional two-role mode:** stages 0–1 with decompilers and REA, stages 2+ in a fresh session
   without them and without `vendor/`. REA itself does not do this; it would be the harness's
   addition.

Exit check (proposed): a scripted run of jira-re with a synthetic jar completes all 7 stages, and:
- pre-flight lists `rea` as connected;
- tier-2 scores, the JUnit own-suite rerun and the similarity score appear at every checkpoint;
- `pytest` and `-m local` are green.

## 8. Open decisions for the owner

1. **What "clean room version" means for the build.**
   - **(a), drafted:** a JDK-only rewrite with its own Jira interfaces. It builds offline today.
   - **(b):** a real Jira plugin. It would need the Jira API jars and their dependencies pre-fetched
     into an offline local Maven repository in the toolchain, with a pinned Jira version. That is much
     larger, but the rewrite could then be deployed in place of the original.
2. **One agent or two roles** (§7.5). REA's model is one agent.
3. **REA's role** given that its JVM support is APK-only: keep it as an optional extra channel, or wrap
   the jar as a DEX/APK so REA's Android tools can open it.
4. **Budgets:** the owner expects them to be large. The spec carries placeholders (360 min, $250) until
   the owner sets the figures. Real runs need spend approval.
