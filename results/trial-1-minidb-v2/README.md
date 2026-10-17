# Trial 1: minidb v2, first real run

The first real long run of the framework: Claude Code CLI 2.1.301, model `claude-opus-5-5`,
config A, building the staged SQL engine task (`fixtures/tasks/minidb_v2`), 17 Oct 2026.

**Start here:** [`reports/executive-report.html`](reports/executive-report.html) (the early-feedback
report for executives) and [`reports/dashboard.html`](reports/dashboard.html) (all charts). Open them
in a browser after cloning; GitHub shows HTML as source.

## Result in one paragraph

The agent ran 98 minutes and was stopped by the $40 (estimated, API-equivalent) cost cap during the
last of seven stages. No test that once passed ever failed again across 48 commits and two change
requests, and there were no policy violations. The first degradations were cost (cost per accepted
commit rose five-fold as the agent's context grew from 17% to 70% of its 1M-token window) and one
rule from the start of the session that it broke twice. 192 of 201 hidden tests passed at the stop;
the 9 failing belonged to the stage delivered 4 minutes earlier.

This run used the original fixed-time stage schedule, so the agent spent about half the time idle
between stages. The framework now sends each stage as soon as the previous one is done.

## What is here

| Path | Contents |
|---|---|
| `reports/executive-report.html` | Early-feedback report (one run; no confidence interval yet) |
| `reports/dashboard.html`, `reports/figures/` | Dashboard: survival, metric strips, cost, context fill, test heatmap, per-tier pass rates, belief gap |
| `reports/report.pdf` | One-page PDF summary |
| `run/manifest.json` | Run identity, versions, spec, start/end, final state, cost |
| `run/events/` | Append-only logs: orchestrator, agent stream (every message and tool call), telemetry, guardrail, scorer |
| `run/snapshots/t1` … `t5` | The agent's code at each checkpoint (t5 = the moment the cost cap stopped it) |
| `run/mirror.git` | The agent's full git history (48 commits), a bare repo: `git --git-dir run/mirror.git log ckpt/t5` |
| `run/scorer/` | Scorer caches (judge answers, per-commit results) |

## What was changed in this copy

- The account email in the CLI's session transcripts (`run/snapshots/*/agent_state/`) is replaced
  with `[REDACTED]`. Telemetry account identifiers were already redacted when the run was recorded.
- The snapshots' own `.git` folders and Python caches are left out (git cannot store a repository
  inside a repository); the full history is in `run/mirror.git`.
- Local paths such as `/Users/...` appear in some logs; they identify the machine the run used.

The original artifacts stay on the machine that ran them, in `runs/` (not committed).

## Rebuilding the numbers

From the repo root, with this folder copied into `runs/`:

```bash
mkdir -p runs && cp -R results/trial-1-minidb-v2/run runs/minidb-v2-early-A-r00-338286d0
.venv/bin/lrae ingest && .venv/bin/lrae dashboard minidb-v2-early
```
