# Phase JR1: first jira-re pilot run

**Date:** 2026-11-02 · **Branch:** `jira-re` (commit `81fc999`) · **Run:** `jira-re-pilot-A-r00-acdffb93` · **Previous:** JCR1

**Exit check (stated at the start):** one real run of `spec/examples/jira-re.yaml` inside the owner's $100 budget, scored at
every checkpoint, with the artifacts kept on this machine.

**Result: met, but the run stopped at the budget in stage 2.** The task is too large for a $75 agent cap.

## Budget (owner, 2026-11-02)

$100 in all, lowered from $200: an agent hard cap of $75 (`per_run_usd` = `experiment_usd` = 75; `experiment_usd` counts agent
spend only) and judges estimated at $10-25, which have no cap.

| | spend |
|---|---|
| agent (Opus 5.5, cap $75) | $75.21 (logs) / $75.13 (store) |
| behaviour judges | $1.77 |
| code judge (3 samples × 5 checkpoints) | $2.49 |
| **total** | **about $79.5** |

## What happened

| stage | delivered | turn length | notes |
|---|---|---|---|
| 0 | 14:16:56 | 11.5 min | plan; 5 subagents (foreground) read the claims; $7.97 |
| 1 | 14:28:24 | 33 min | plugin key, offline deps, OSGi exports, the public API (generated from `spec/API.md` by a tool it wrote), all 608 modules as placeholders, the AO schema |
| 2 | 15:01:45 | stopped at 15:56:38 | shared infrastructure, then **7 background subagents** in two waves |

- **Final state:** `BUDGET_EXHAUSTED` after 100 min. 5 checkpoints, all scored without errors.
- **Spend rate:** about $25 an hour until 15:10, then about $75 an hour while the five parallel subagents of 15:12 ran. Agent
  tokens came to 171M, 97% of them cache reads.
- **Hidden suite at checkpoint 5:** 1,061 passed, 0 failed, 290 skipped (later stages, or modules not yet done).
  - t04 contract: 609 passed.
  - t05 API signatures: 417 passed.
  - t08 claim tests: **33 of 87 passed**; the other 54 were skipped because those modules aren't done yet.
  - Commits in between failed t02 "at least a third rewritten" 7 times.
- **Constraints:** `C` = 1 from checkpoint 1 onwards, very likely `classes-need-tests` (419 main classes against 4 test files at
  checkpoint 1). The `pom_pinned` check confirms the pinned properties are unchanged.
- **Copy similarity:** structural 0.006 rising to 0.028, lexical below 0.01. That fits a clean room with no jar.
- **Rework `W`:** 0.03. Goal fidelity 0.92 rising to 0.95.
- **Clean-up:** work dir removed and agent state snapshotted and deleted (D-15); no processes left.

## Guardrails (all log-only apart from the budget kill)

- `other-outside`, 122+: mostly listing and reading the offline Maven repository.
- `own-transcript`, 16: reads of saved tool output (allowed, D-26).
- `decompiler`, 38+: `javap` on **published libraries** in the offline repository (Jira API, Active Objects, atlassian-cache,
  streams, `integers`) to read signatures. No original plugin code.
- **`outbound-connection`, 12: an environment problem.** Maven (`build.sh` passes `-o`) opened HTTPS connections, some
  established, to Cloudflare and CloudFront addresses during `package`. Nothing was written to `~/lrae-tools/re/m2`. Which plugin
  makes these calls is not known yet.

## Unresolved, and proposals

1. **$75 does not cover the task.** At these rates a full run (stages 0-6) needs roughly $200-350, and stage 5 (the change request)
   was never reached. **Proposal:** before the next run, either raise the budget or shrink the pilot (for example the 23-claim
   `structure-info` slice plus one group). This is the owner's call.
2. **Parallel subagents triple the spend rate.** The task doesn't forbid them. **Proposal:** decide whether the task should
   limit them (a rule in the seed's CLAUDE.md) or whether this is behaviour to measure as it is.
3. **The build reaches the network despite `-o`.** Find the plugin that does this and block it (an AMPS or analytics setting, or
   a proxy that refuses connections). Until then the build environment isn't really offline.
4. **Scoring a checkpoint now takes 8-20 minutes,** up from 2-3 at checkpoint 1. With 18 checkpoints that could fall behind
   the 20-min interval.
5. **Done after the run (owner, 2026-11-02): reads under `task.toolchain.dir` no longer raise `other-outside`.** Writes there still
   do. Replaying this run's 1,086 tool calls: `other-outside` 135 → 5, `decompiler` 42 and `own-transcript` 16 unchanged. Of the 5
   left, one is real (`find ~ -maxdepth 6` from a subagent); the rest are false hits in `sed` scripts (`s/var …` read as `/var`), a
   parser gap left for later. This run's logs keep their counts, so `outside_paths` isn't comparable across the change.
6. **What `C` = 1 counts:** the scorer's output doesn't name the broken probe, so I had to infer it. Name it in the score.

No spec decision (D-n) was changed.
