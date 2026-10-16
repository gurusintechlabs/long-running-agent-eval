# Calibration (Phase 4)

**Status: method fixed, numbers pending.** Every threshold below must come from real-agent data: the
dry run and the 2-repeat pilot (docs/plan.md Phase 4 tasks 2–3). Neither has run yet, because both
need owner approval of subscription spend. The scripted pilot only proves the pipeline. Its
numbers are synthetic and must **not** be used to calibrate.

Any change below goes into a **new spec** (new `spec_hash`), never into `pilot.yaml` in place.

## 1. Budget caps (`budget.per_run_usd`, `per_run_tokens`)

- **Input:** dry run `spec/examples/dryrun.yaml` (15 min, config A, one repeat, cap $8 estimated).
- **Measure** (from `runs/metrics.sqlite`, table `counters`):
  - tokens/hour = Σ `tokens_*` ÷ run hours;
  - estimated $/hour = Σ `cost_usd` ÷ run hours;
  - also the peak 5-minute interval.
- **Set:**
  - `per_run_usd` = 1.5 × ($/hour × run hours);
  - `per_run_tokens` = 1.5 × (tokens/hour × run hours);
  - `experiment_usd` = repeats × configs × `per_run_usd`.
- **Subscription window (D-16):** record what share of the usage window the dry run used, from the CLI's own `/usage` output, read by the owner. Extrapolate to 60 min. If one pilot run does not fit in a window, shorten the pilot before running it.

## 2. `repeat_work_ratio` (W hazard; default 0.30)

- **Input:** W per checkpoint for both pilot repeats.
- **Rule:** set the threshold above the 95th percentile of W over checkpoints that a human reviewer judges to be *healthy* progress (refactors that delete the agent's own earlier lines are normal). Report the share of checkpoints that would fire at 0.2, 0.3 and 0.5.
- The scripted pilot shows W = 0.33 and 0.5 at t5–t6 from a deliberately churned notes file, which proves only that the metric moves.

## 3. Cost baseline and `cost_per_commit_multiplier` (default 2.0, baseline over 2 checkpoints)

- **Baseline definition (implemented):** pooled Σ interval cost ÷ Σ accepted commits over the first `cost_baseline_checkpoints` checkpoints that have ≥ 1 accepted commit.
- **Rule:** look at `S_int` across all pilot intervals after the baseline. Set the multiplier so that a typical healthy run does not fire (> the 90th percentile of `S_int / baseline`).
- If accepted commits are too rare for a stable baseline (< 3 per baseline window), propose a longer baseline window instead.

## 4. Should D (defect density) become a hazard?

- D is tracked but is not a hazard trigger in v1.
- **Proposal rule:** make D a hazard only if `D_delta` (vs seed) rises monotonically in at least one pilot run and a reviewer confirms that the new findings are real defects rather than style.

## 5. Telemetry-silence threshold (Phase 2 open item)

From the pilot's `otel.jsonl`, measure the longest gap between OTel records while a turn is active. If that gap is regularly above 60 s, keep the Phase 2 rule (pause on silence only when the receiver is down) and amend spec §7.2.

## 6. Stability across repeats (Phase 4 exit; spec §15 Q3 definition)

- Re-scoring is deterministic for P/R/D/C/W/S, and X stays within its spread. **Checked on the scripted pilot:** `lrae score <run> --check-determinism` gave identical values at all 12 checkpoints.
- No metric is missing: 7 × 6 × 2 values with no nulls. **Checked on the scripted pilot.**
- Differences between real repeats are explained: **pending the real pilot.**
