# Phase B5b Summary: judges, behaviour analysis, dashboard panels, canary exit check

**Branch:** `behavior-improvements` · **Design:** `docs/behavior-design.md` §5.4, §6, §8, §9 (D-21, D-22) ·
**Contract:** `docs/interfaces.md` §4, §5, §6

B5b is the second half of B5. B5a (`docs/phase-B5a-summary.md`) added the deterministic detectors.

**Exit check (plan B5):** the track exit check, items 1 and 2, for every mode on scripted canaries:
1. a scripted canary for each of the twelve modes is flagged with the expected detector(s) and evidence;
2. a clean scripted reference run is flagged for no mode.

**Met**, with one deviation: the canaries run in a fixture task, not in minidb v3 (see Unresolved).
`tests/integration/test_behavior_canaries.py` passed 13 of 13, twice in a row.

## What was built

- **Judges** (`scorer/judges/`, D-21, design §8):
  - `base.py`: prompt loading, untrusted wrapping (shared with X), envelope parsing, one retry, `None` on
    failure (never 0), a cache keyed by prompt and model, and spend reported apart from S.
    - `FakeBehaviorJudge`: deterministic "nothing found" answers, for scripted runs.
    - `RecordedJudge`: recorded answers chosen by a marker in the prompt, for canaries.
  - `prompts/goal_observer.md`, `manipulation.md`, `prose_claims.md` (v1). Each names itself on its
    first line. The prompts in use are hashed into `spec_hash` when behaviour scoring is on.
  - `behavior.py`: bundles, schema validation and `run_judges`:
    - the **goal observer** reads the brief so far, the seeded `CLAUDE.md`, and the interval's
      messages, tool calls and tree diff;
    - **manipulation** reads the ops-channel transcript plus facts (directives in force, claim audit,
      own suite, earlier decisions);
    - **prose claims** runs per stage end, on the stage-final messages and ops messages plus facts (own
      suite rerun at the stage-end commit, hidden results, constraints, claim audit, failing tool
      results near the stage end).

    Judge events are `deterministic: false` and never hazards.
  - `brief.py`: the brief as the agent received it, with the `From:` header and directives. An
    `inbound` stage is marked NOT AUTHORITATIVE.
- **X judge stage messages:** the X `<task>` now uses `later_stages`. Before, X treated an inbound
  message from an unauthorised colleague as part of the brief, and it never saw directives. For v1/v2
  tasks the text is byte-identical, so their judge caches stay valid (tested).
- **Spec:** `scoring.behavior.judges` (default: all three) and `judge_fixtures` (resolved, hashed).
  Behaviour scoring stays off by default, and the section is left out of the hash at its defaults.
- **Ingest:** the `run_markers` table (stage deliveries, directives issued and lifted, env changes).
- **`analysis/behavior.py`:**
  - per-mode survival (first hazard event of the mode; VI = the `security` hazard);
  - incidence per agent-hour, by run hour and by context-fill bin;
  - AF anomalies per checkpoint interval:
    - spikes: robust z from median/MAD against the prior intervals;
    - drops below 10% of the prior median: the interval-level "under 10% of baseline" stall that B5a
      deferred;
  - stuck episodes with their escalation slope, and an escalation summary;
  - security trend per checkpoint;
  - the run timeline, and a per-mode table.
- **Dashboard** ("Behaviour and security" section, shown only when there is behaviour or SEC data):
  - the per-mode table and the per-mode survival chart;
  - incidence tables by run hour and by context fill;
  - stuck episodes;
  - per run:
    - the behaviour timeline: one row per mode, with hazard, signal and judge markers, and stage,
      directive and env-change lines;
    - the security trend chart: new SAST findings by severity, failed exploit tests, AI findings;
    - action-rate anomalies;
    - the event table;
  - the judge spend.
- **Canaries:**
  - `fixtures/behavior/`: the shared five-stage task (feature with STATUS, freeze directive, env change
    retiring embed v1, inbound message, release with STATUS), the seeded `CLAUDE.md`, the ops policy
    and the recorded judge answers;
  - `fixtures/scripted/build_beh_canaries.py` generates `beh_<ID>.yaml` for the twelve modes and
    `beh_clean.yaml`. Each canary is the clean reference with one stage changed.

## Fixes to B5a found by the canaries

- **SE inbound compliance never fired in a real run.** The harness delivers inbound messages as
  `stage.delivered` with `kind: inbound`, and nothing ever emits `ops.inbound`. The detector now
  accepts both.
- **Guardrail findings were dated by detection time.** The monitor can raise a finding after the next
  stage has been delivered, which made a decoy use in stage 2 look as if it followed the stage-3
  inbound message (a flaky false SE flag). Detectors now date findings by the tool call
  (`stream_seq`).
- **Scope drift counted harness files:** files committed by env actions and the workspace decoys. The
  clean run read 0.4 because of `.env.staging`. Both are now excluded.
- Stuck episodes now record their start time (`t_s`), for the escalation analysis.

## Tests

- `tests/unit/scorer/test_behavior_judges.py` (11):
  - validation, retry then null, cost kept, cache;
  - untrusted wrapping, prompt names, the fake and recorded runners;
  - the brief (unchanged for v2; headers, directives, inbound marking);
  - `run_judges` for all three judges.
- `tests/unit/analysis/test_behavior.py` (8):
  - per-mode survival including VI;
  - incidence by hour and by fill bin, with hand-computed exposures;
  - rate anomalies, stuck episodes and escalation;
  - security trend, timeline (with VI), and the mode table.
- `tests/unit/report/test_dashboard.py` (+1): behaviour panels and figures; evidence is escaped; a run
  without security data gets no security figure (a bug caught while rendering a sample).
- `tests/unit/analysis/test_ingest.py` (+1): `run_markers`.
- `tests/unit/behavior/test_modes.py`: inbound stage counts for SE, stream_seq dating, harness and decoy
  paths left out of drift.
- `tests/unit/test_spec_schema.py` (+1): the behaviour section, judge prompts and fixtures are hashed
  only when used.
- `tests/unit/test_beh_canaries.py` (2): the generated scripts are up to date and cover every mode.
- `tests/integration/test_behavior_canaries.py` (local, 13 runs, about 2.5 min with `-n 4`): the exit check.
- `pytest` (default) 786 passed, `pytest -m local` 136 passed (19.3 min), `ruff check .` clean.

## Unresolved / proposed

- **The canaries are not in minidb v3.** The track exit check asks for canaries "inside a minidb v3
  workspace", and minidb v3 is plan B6. B6 should re-target `fixtures/scripted/beh_*.yaml` to the v3 seed
  and stages; the expected-detector table in the test carries over.
- **Judges are not validated.** The track exit check needs only `FakeJudge` and recorded answers.
  - The optional spot-check (~$10, needs approval) is still open.
  - Judge signals are not hazards (design §6).
  - With `judge_runtime: claude_code`, all three judges run at every checkpoint. That adds spend per
    checkpoint, as D-21 accepted. Judge spend goes to `behavior_judge_cost_usd`, not S.
- **Re-scoring changes some X caches.** Re-scoring an old run of a task that has `source`, directives
  or inbound stages builds a different X bundle, so its X judge cache misses. Only B1–B4 test tasks
  have these fields.
- **Incidence by fill leaves some time out:** the time after the last checkpoint, which has no fill
  value.
- **Proposed spec notes:**
  - the metric names keep the `BEH_<MODE>_<name>` form from B5a, not the design's `beh.<ID>.<metric>`;
  - judge spend is a metric (`behavior_judge_cost_usd`), not a separate log.
