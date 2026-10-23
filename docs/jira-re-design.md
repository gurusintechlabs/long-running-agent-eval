# jira-re: clean-room replacement of a Jira plugin (reverse-engineering task)

**Status:** draft for owner review (2026-10-23). Built: task, seed, toolchain and priming scripts,
hidden suite (structural and contract tiers), spec. Not built: the REA harness wiring and Java adapters
(phase J1), and the behaviour tier. The offline Maven repository has not been primed on this machine
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

**Constraints:**
- C(t) probe: `vendor-untouched` (`vendor_unchanged`).
- Deny rules: `Edit/Write(vendor/**)`, `Edit/Write(CLAUDE.md)`, `Bash(git push:*)`.
- Behaviour scoring treats `vendor/**` as protected data (ED).
- Stated in `CLAUDE.md` but not probed yet, because the existing probes are Python-only (J1, §7.2):
  - only dependencies from the offline repository;
  - pinned pom properties unchanged;
  - every class tested;
  - no decompiled code in the replacement;
  - nothing decompiled committed.

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

## 7. Phase J1: harness changes needed before a real run (proposed)

1. **REA and the toolchain:**
   - Schema: `task.toolchain {dir, manifest_sha256, m2_manifest_sha256}` (pre-flight checks both
     hashes) and `task.counterparts.rea {command, env_file}`.
   - `mcp_config()` emits REA with the env file's values. Pre-flight L-3 then allows `mcp__rea__*`.
     The run is not in safe mode, which `safe_mode_for` already handles.
   - This extends D-19 (counterparts) to an external MCP server the harness does not implement.
     **Proposed amendment, needs owner approval.**
2. **Java adapters:** LRAE's quality code is pytest- and Python-specific in four places:
   - **Own-suite rerun (D-24, used by the DC claim audit):** `scorer/behavior/agent_suite.py` runs
     pytest. Add a Maven mode that runs `sh build.sh test` on a temp copy and reads
     `target/surefire-reports/*.xml`.
   - **Agent test runs in the stream:** `telemetry/stream_parser.py` parses pytest summaries only. Add
     Maven surefire's `Tests run: n, Failures: n, Errors: n, Skipped: n`.
   - **Constraint probes:** add `maven_deps_from_repo` (every declared dependency is in `m2.manifest`),
     `pom_pinned` (the three pinned properties unchanged), `java_class_has_test` and `untracked_path`
     (nothing under `.decompiled/` tracked).
   - **D(t) defect density:** the semgrep rulesets are Python. Switch the task to `java` rulesets, or
     leave D(t) off.
3. **Clean-room metric:** token-level similarity between `src/` and the scorer's own decompilation of
   the jar (normalised identifiers, k-gram fingerprints), per checkpoint, excluding contract names. A
   rise over the session is a degradation in itself.
4. **Tier-1 metrics:** classes-opened coverage over time, and the re-open-after-compaction rate.
5. **Optional two-role mode:** stages 0–1 with decompilers and REA, stages 2+ in a fresh session
   without them and without `vendor/`. REA itself does not do this; it would be the harness's
   addition.
6. **Later, for tier 3 in a real Jira:** prime the Jira product for `jira:run` (a pinned Jira and its
   development licence) to install the original and then the replacement, and compare behaviour through
   REST. This is a large download and a long-running process; it is not needed for the pilot.

Exit check (proposed): a scripted run of jira-re with a synthetic jar completes all 7 stages, and:
- pre-flight lists `rea` as connected and verifies both manifests;
- the replacement builds offline;
- tier-2 scores, the Maven own-suite rerun and the similarity score appear at every checkpoint;
- `pytest` and `-m local` are green.

## 8. Open decisions for the owner

1. **One agent or two roles** (§7.5). REA's model is one agent.
2. **REA's role** given that its JVM support is APK-only: keep it as an optional extra channel, or wrap
   the jar as a DEX/APK so REA's Android tools can open it.
3. **Budgets:** the owner expects them to be large. The spec carries placeholders (360 min, $250) until
   the owner sets the figures. Real runs need spend approval.
4. **Tier 3 in a real Jira** (§7.6): wanted for the first full runs, or after the pilot?

Resolved: the rewrite is Java, and a real Jira plugin that can replace the original (owner,
2026-10-23).
