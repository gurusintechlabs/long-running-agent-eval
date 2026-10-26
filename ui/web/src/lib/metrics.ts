import type { CheckpointRow } from "../api";

/** The headline metrics of docs/spec.md §8.3, in display order. */
export const CORE_METRICS = ["P", "R", "D", "C", "W", "X", "S"] as const;

export const METRIC_LABELS: Record<string, string> = {
  P: "Hidden pass rate",
  R: "Regressions",
  D: "Defect density",
  C: "Constraint violations",
  W: "Repeat-work ratio",
  X: "Contradictions (judge)",
  S: "Cost per accepted commit",
  S_int: "Cost per commit (interval)",
  D_delta: "Defect density vs seed",
  W_repeat_tool_calls: "Repeated tool calls",
  X_spread: "Judge spread",
  accepted_commits: "Accepted commits",
  tests_tampered: "Tests tampered",
  tokens_per_commit: "Tokens per commit",
};

export function metricLabel(name: string): string {
  return METRIC_LABELS[name] ?? name;
}

/** Metric names present in the checkpoints: core ones first (in order), then the rest alphabetically. */
export function availableMetrics(cps: CheckpointRow[]): string[] {
  const seen = new Set<string>();
  for (const c of cps) for (const k of Object.keys(c.metrics)) seen.add(k);
  const core = CORE_METRICS.filter((m) => seen.has(m));
  const rest = [...seen].filter((m) => !(CORE_METRICS as readonly string[]).includes(m)).sort();
  return [...core, ...rest];
}

/** [t_minutes, value] pairs for one metric; checkpoints without the metric are skipped. */
export function seriesFor(cps: CheckpointRow[], metric: string): [number, number][] {
  const out: [number, number][] = [];
  for (const c of cps) {
    const v = c.metrics[metric];
    if (typeof v === "number" && Number.isFinite(v)) out.push([(c.t_s ?? c.k) / 60, v]);
  }
  return out;
}
