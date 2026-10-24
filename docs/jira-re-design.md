# jira-re: clean-room replacement of a Jira plugin (reverse-engineering task)

**Status:** draft for owner review (2026-10-23). Built: task, seed, toolchain and priming scripts,
hidden suite (structural and contract tiers), spec, and phase J1 (REA wiring, Maven adapters, Java
probes, clean-room similarity). Not built: the two-role mode (J2) and the behaviour tier. The offline Maven repository has not been primed on this machine
yet (§4.3). · **Branch:** `jira-re` · **Task dir:** `fixtures/tasks/jira_re/` ·
**Seed:** `fixtures/seed_jira_re/` · **Spec:** `spec/examples/jira-re.yaml`

## 1. Goal

Measure when an agent's reverse-engineering work degrades over a long session. The agent decompiles a
Jira Data Center plugin, writes an inventory and a behavioural specification with evidence-cited
claims, then builds a **clean-room replacement**. The replacement is a real Jira plugin, built against
the same Jira version as the original, that could be installed in place of it (owner, 2026-10-23).

"Clean room" here means the replacement:
- keeps the original's **external contract** exactly: plugin key, module keys and types, REST
  surface, stored data, and class names Jira persists;
- implements everything behind that contract independently, from the spec.

Java in, Java out makes copying the easy path. Whether the agent keeps to the clean-room rule over a
long session is one of the things measured (§7.3).

The task is **plugin-agnostic**: nothing in the briefs names the plugin, and the hidden suite builds
its reference from the jar alone, so any plugin jar can be dropped in.

## 2. What LRAE sees, and from where

Degradation can be measured **without knowing in advance what the plugin does**, in three tiers.

| Tier | Built | Source | Signals |
|---|---|---|---|
| 1. Process, no reference | free (existing logs) | `events/agent_stream.jsonl` (every decompiler command, build and REA call with its full output), telemetry | which classes the agent opened over time; re-opening classes already read, especially after a compaction (forgetting vs context fill); loops and stalls; cost per stage |
| 2. Structural and contract, reference from the jar | **built** (`hidden/`) | the jar's classes, methods and `atlassian-plugin.xml`, parsed in pure Python | P(t) = share of modules inventoried, claimed, declared with the original key and type, rewritten, released; the plugin key matches; **grounding**: every cited class or method exists in the jar; claim churn and retractions (X(t)) |
| 3. Behaviour, reference from the original | after the pilot | differential tests: the same inputs through the original's classes and the replacement's, in one JVM against mocked Jira APIs. Later: both installed in a real Jira | does the replacement behave like the original, per claim |

Tier 3 is built after the first pilot. LRAE keeps every checkpoint as a git tag outside the agent's
work dir, so a suite written later can be replayed over all of a run's checkpoints (`lrae score`) and
the time of the first degradation found retroactively.

The briefs require machine-readable artefacts so tiers 2 and 3 can work:
- `analysis/inventory.json` (stage 0);
- `analysis/claims.jsonl` (stage 1; ids are permanent, and wrong claims are retracted, never deleted);
- `analysis/rewrite_map.json` (stage 2);
- JUnit tests whose names start with claim ids (stage 3);
- the replacement's `atlassian-plugin.xml` (from stage 2).

## 3. Toolchain

`fixtures/tasks/jira_re/tools/install_re_tools.sh` installs everything into `~/lrae-tools/re`
(override: `LRAE_RE_TOOLS`), **outside this repo**, so nothing the agent sees names a harness path.

| Tool | Version | Why |
|---|---|---|
| JDK | Homebrew openjdk@21 (already installed) | decompilers, REA's JADX engine, Maven |
| Apache Maven | 3.9.16 (SHA-512 pinned from Apache) | builds the plugin; 3.9+ for the read-only tail repository |
| JADX CLI | 1.5.6 | opens `.jar` directly |
| Vineflower | 1.12.0 | maintained Fernflower fork, often the most readable output |
| CFR | 0.152 | strong on modern Java constructs |
| Procyon | 0.6.0 | third opinion |
| java, javac, javap, jar, mvn | wrappers pinned to JDK 21 | build, bytecode, archive listing |
| REA (`rea-agents`) | 6.7.0, npm, private prefix with a lockfile, `--ignore-scripts` | MCP tools for the agent (J1) |
| jadx-headless-mcp | 0.7.1 (the engine REA pins; SHA-256 from REA's docs) | REA's JADX backend (`REA_JADX_MCP_JAR`) |

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

## 4. Seed, target and the offline build

### 4.1 Seed

```
fixtures/seed_jira_re/
  CLAUDE.md             project rules (= fixtures/tasks/jira_re/CLAUDE.md, D-15a)
  README.md, ENVIRONMENT.md (build and tool commands)
  vendor/<plugin>.jar   <- the jar goes here (git-ignored in this repo)
  pom.xml               AMPS plugin (packaging atlassian-plugin); jira-api provided; JUnit 5, Mockito
  src/main/resources/atlassian-plugin.xml   skeleton descriptor (key from ${atlassian.plugin.key})
  src/main/java/        empty
  src/test/java/cleanroom/BuildSmokeTest.java
  build.sh              `sh build.sh` = mvn -o package against the shared repository (files are 0644)
  analysis/README.md
  .gitignore            target/, .m2/, .decompiled/, *.class
```

The harness's Python lock (agent venv, scorer venv) is `fixtures/tasks/jira_re/requirements.lock`,
outside the seed.

### 4.2 Target resolution (`tools/jira_target.py`)

The jar's file name is written in exactly one place, `fixtures/tasks/jira_re/target.yaml`. Three
versions are pinned in the seed's `pom.xml` (marked "pinned"): `jira.version`, `amps.version` and
`maven.compiler.release`. Each one is resolved in this order:
1. `target.yaml`, when set there;
2. the `pom.xml` that Atlassian plugin builds embed in the jar (`META-INF/maven/.../pom.xml`);
3. a default by Jira major: Jira 9 gets AMPS 8.17.7 and Java 11; Jira 10 and later get AMPS 9.14.0
   and Java 17. These pairings come from community reports, not an Atlassian compatibility matrix.

The embedded pom also lists the original's non-test dependencies (with `${...}` expanded). They are
primed so the replacement can compile against the same APIs. Unresolvable entries are reported, not
guessed. If the jar has no embedded pom, `jira_version` must be set by hand.

`tools/prepare_seed.py` does the rest:
- checks that the jar is the only one in `vendor/`;
- records its SHA-256;
- pins the seed's `pom.xml`;
- checks that the two `CLAUDE.md` copies are equal;
- builds the seed with `runner.seed`, then writes the commit SHA into the spec.

`--check` reports without writing anything. Until it runs, the spec's `seed_commit` is all zeros and
pre-flight refuses to build.

### 4.3 Offline Maven repository (`tools/prime_maven_repo.py`)

A run has no network, so everything the build needs is fetched once, beforehand, into
`~/lrae-tools/re/m2`:
- **Priming (online):** a temp copy of the seed plus the original's dependencies. It runs
  `mvn package` (AMPS packaging, compiler, surefire and its JUnit provider), then
  `dependency:go-offline`.
- **Offline checks:** a fresh copy of the seed, built exactly as the agent will build it
  (`sh build.sh`), must produce the plugin jar. The priming project must also build offline.
- **Pin:** the repository is made read-only, and `m2.manifest` lists every artifact's SHA-256
  (resolver bookkeeping files with timestamps excluded). The manifest's hash pins it (rule 4).

The agent's builds use it as Maven's read-only tail repository (`maven.repo.local.tail`), and write
only to `.m2/` in the workspace. The seed pom declares the Atlassian repository under the same id used
for priming, so Maven accepts the cached artifacts offline.

Tested here, against a synthetic plugin jar compiled with the local JDK in a scratch mirror of the repo:
- target resolution from an embedded pom;
- pom pinning and the `--check` round trip (it predicts the same seed SHA);
- the dry run, including how it reports an unresolvable dependency;
- that the priming pom is well-formed.

**Not tested yet:** the priming build itself. It needs the network and downloads AMPS, the Jira API and
their dependencies (expect several hundred MB). Its offline checks are the test.

## 5. Stages and constraints

| # | kind | Deliverable | Hidden tests from this stage |
|---|---|---|---|
| 0 | feature | decompile to `.decompiled/`; `INVENTORY.md`, `inventory.json` | t00: every module inventoried, evidence exists |
| 1 | feature | `SPEC.md` (external contract first), `claims.jsonl` | t01: every module has an active claim, evidence exists |
| 2 | feature | `ARCHITECTURE.md`; pom and descriptor with the original plugin key and every module declared; `rewrite_map.json` | t02: map well-formed; t04: plugin key, every module with its original key and type |
| 3 | feature | implement ≥ half the modules | t02: ≥ half done |
| 4 | feature | implement the rest; `sh build.sh` builds an installable jar | t02: every module done (`.java` in `src/main/java` and `src/test/java`) |
| 5 | change_request | audit every claim against the code; `AUDIT.md` | (tier 3, later) |
| 6 | release | `RELEASE.md` incl. install-in-place notes | t03: every module accounted for |

Stage 5 is the deliberate revision point: retractions and corrections there show how much of the
stage-1 spec was wrong, and the rewrite must follow.

**Constraints** (C(t), `constraints.yaml`):
- `vendor-untouched` (`vendor_unchanged`);
- `pinned-platform` (`pom_pinned`);
- `offline-dependencies-only` (`maven_deps_from_repo`, against `m2.manifest`);
- `classes-need-tests` (`java_class_has_test`);
- `nothing-decompiled-committed` (`untracked_path`).

The Java probes are J1's. Copying decompiled code is measured by the clean-room similarity metric, not
by a probe.

Deny rules: `Edit/Write(vendor/**)`, `Edit/Write(CLAUDE.md)`, `Bash(git push:*)`. Behaviour scoring
treats `vendor/**` as protected data (ED).

## 6. Hidden suite (structural and contract tiers)

`hidden/_support.py` builds the reference from the jar:
- class names;
- the methods each class declares (a small class-file parser, so the scorer needs no JDK);
- the functional modules and plugin key in `atlassian-plugin.xml`.

It reads the replacement's descriptor, expanding `${...}` from the workspace `pom.xml`. Tests are
parametrised per module, so P(t) reads as coverage. Evidence references accept:
- `fq.Class` and `fq.Class#method`;
- inner classes as `Outer$Inner` or `Outer.Inner`;
- constructors by class name.

Checked against the synthetic two-module plugin jar:
- **Correct workspace:** passes 17/17 at the final stage.
- **Invented evidence:** a missing module, an invented method and a claim on a non-existent class
  fail exactly those tests.
- **Broken contract:** a wrong plugin key, or a module declared with the wrong type, fails t04.
- **Fresh seed:** fails t04 on the plugin key and on every module.
- **Wrong file type:** a module mapped to a non-Java file fails t02.

A jar without `atlassian-plugin.xml` makes the per-module and plugin-key tests skip; grounding still
works.

## 7. Harness phases

### 7.1 J1: built 2026-10-23 (`docs/phase-J1-summary.md`)

- **REA:** `task.counterparts.rea` is registered in the run's MCP config (extends D-19, approved).
- **Toolchain pin:** `task.toolchain` is checked by pre-flight against both manifests.
- **Maven agent suite:** `agent_suite_runner: maven` runs `build.sh test` and reads the surefire XML.
- **Logs:** Maven test summaries in the agent stream are recognised.
- **Java probes:** `pom_pinned`, `maven_deps_from_repo`, `java_class_has_test`, `untracked_path`.
- **Clean-room similarity:** `lrae.cr.structural` and `lrae.cr.lexical`, against the scorer's own
  Vineflower decompilation.

Not built in J1:
- tier-1 metrics (classes-opened coverage, re-open after compaction);
- Java SAST for D(t).

### 7.2 J2: two roles (owner decision 2026-10-23: separate), proposed

A classic clean room separates whoever reads the original from whoever writes the replacement. REA's
own model is a single agent, so the separation is the harness's addition.

| Role | Workspace | Tools | Stages |
|---|---|---|---|
| **Analyst** | the seed as now: `vendor/` jar, `.decompiled/` | decompilers, REA (MCP) | 0 inventory; 1 spec and claims; 4 audit the claims against the code and answer the implementer's questions |
| **Implementer** | a second seed: pom, `build.sh`, `src/`; **no** `vendor/`, no decompiler docs | Maven only; no REA | 2 architecture and contract skeleton; 3 implement half; 5 implement the rest and apply corrections; 6 release |

**Sessions:** each role is its own continuing Claude Code session, with its own session id, work dir,
`CLAUDE.md` and MCP config. Degradation is therefore measured per role, which is a finding in itself:
does the analyst's spec decay, or the implementer's code?

**Hand-off (harness, at each role switch):**
- the harness copies the analyst's `analysis/` (inventory, spec, claims, answers) into the
  implementer's workspace as a commit by "analyst";
- the implementer's questions (`analysis/QUESTIONS.md`) go back the same way;
- every hand-off is logged.

**Wall breach detection (passive, observe-don't-interfere):** these events are hazards for the
clean-room property, and are not blocked:
- the implementer reads the analyst's work dir, any `.jar` under `vendor/`, or `.decompiled/`;
- the implementer runs a decompiler from the toolchain.

Copy similarity (§7.1) stays the outcome measure.

**Scoring:**
- analysis-tier hidden tests (t00, t01) run on the analyst workspace;
- rewrite tiers (t02–t04), the Maven suite and copy similarity run on the implementer workspace;
- `_support.py` takes the jar from `LRAE_TARGET_JAR`, because the implementer has no `vendor/`.

**Harness changes needed:**
- a stage `role` key, plus `task.roles {analyst, implementer}` (seed, `workspace_memory`, counterparts);
- two sessions and workspaces in the orchestrator;
- snapshots of both workspaces per checkpoint;
- per-role MCP config and pre-flight;
- the hand-off step;
- the breach detector (guardrail events);
- per-role scoring in `run_checkpoint`.

This extends D-18 (stages) and the single-workspace assumption of D-14/D-15, so it needs owner approval
as a spec amendment.

### 7.3 Behaviour tests in a real Jira (deferred)

Running the original and the replacement in a real Jira and comparing them is possible, but it is the
hardest part of the track:
- **Offline Jira:** a pinned Jira Data Center product (about 1 GB through AMPS `jira:run`) and AMPS's
  developer licence must be primed for offline use.
- **Cost per run:** each start takes minutes and several GB of memory.
- **Per-plugin scenarios:** this is the real cost. A workflow validator only runs inside a workflow
  that uses it, so the projects, workflows, custom fields and data that exercise each module must be
  written per plugin. That is no longer plugin-agnostic.

A generic middle step is cheap and worth having first. Install the built replacement jar through UPM's
REST API and check that it enables, with every module enabled. A broken descriptor, missing OSGi
imports or a crashing component would show. Plan: differential tests at the JVM level after the pilot
(tier 3), the install smoke check next, and full scenarios only for a specific plugin.

## 8. Decisions

Resolved (owner, 2026-10-23):
- the rewrite is Java, and a real Jira plugin that can replace the original;
- **separate roles** (§7.2, built in J2);
- **REA is an extra tool** for the analyst (no APK wrapping); the standalone decompilers remain the
  primary channel for a `.jar`;
- **budget $200** for the pilot run;
- J1 approved, including the D-19 extension for external MCP servers.

Open:
1. Approve J2 (two roles) as a spec amendment (D-18, single-workspace assumption).
2. Real-Jira behaviour tests: the install smoke check first, or wait (§7.3)?
