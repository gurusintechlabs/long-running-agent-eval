// U3 data API: test outcome matrix (docs/ui-api-events.md §7).
import { apiFetch } from "./client";
import { qs } from "./query";

export type Outcome = "p" | "f" | "e" | "s" | "-";

export interface TestPoint {
  idx: number;
  t_s: number | null;
  point: "commit" | "checkpoint";
  k: number | null;
  sha: string | null;
  stage: number | null;
}
export interface TestRow {
  id: string;
  tier: string | null;
  /** One char per point: p f e s or -. */
  cells: string;
}
export interface Flip {
  t_s: number | null;
  test_id: string;
  tier: string | null;
  kind: "regression" | "recovery" | string;
}
export interface PassRate {
  t_s: number | null;
  point: string;
  k: number | null;
  stage: number | null;
  passed: number;
  active: number;
  overall: number | null;
  established: number | null;
  tiers: Record<string, [number, number]>;
}

export interface TestsNotIngested {
  run_id: string;
  ingested: false;
  has_outcomes: false;
  suite: string;
  suites: string[];
  reason: string;
}
export interface TestsResponse {
  run_id: string;
  ingested: true;
  has_outcomes: boolean;
  suite: string;
  suites: string[];
  legend: Record<string, string>;
  points: TestPoint[];
  tests: TestRow[];
  tests_truncated: boolean;
  flips: Flip[];
  timelines: {
    test_id: string;
    tier: string | null;
    first_pass_t: number | null;
    regressions: number[];
    recoveries: number[];
    ttfr_s: number | null;
    final_outcome: string | null;
    relapsed: boolean;
  }[];
  pass_rates: PassRate[];
  status_counts: Record<string, number | string | null>[];
  stage_effects: Record<string, number | null>[];
  window_rates: Record<string, number | null>[];
  summary: Record<string, number | null>;
  checkpoints: { k: number; t_s: number | null; head_sha: string | null }[];
  stages: { stage: number; t_s: number | null; interrupted: number | boolean }[];
}

export const testsApi = {
  get: (id: string, suite?: string, signal?: AbortSignal) =>
    apiFetch<TestsResponse | TestsNotIngested>(`/runs/${encodeURIComponent(id)}/tests${qs({ suite })}`, { signal }),
};
