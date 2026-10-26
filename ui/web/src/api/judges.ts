// Judges tab: each LLM judge's conclusions per checkpoint (GET /runs/{id}/judges, ui_server/routes/judges.py).
import { apiFetch } from "./client";

export interface Contradiction {
  earlier?: string;
  later?: string;
  evidence?: string;
  kind?: string;
}
export interface XSample {
  index: number;
  count: number;
  contradictions: Contradiction[];
  cached?: boolean;
  cost_usd?: number;
}
export interface InferredGoal {
  goal?: string;
  evidence?: string;
}
export interface DriftItem {
  instruction?: string;
  instead?: string;
  evidence?: string;
}
export interface Misstatement {
  kind?: string;
  claim?: string;
  fact?: string;
  evidence?: string;
}
export interface ClaimStage {
  stage: number | null;
  misstatements: Misstatement[];
  dropped: Array<Record<string, unknown> | string>;
}
export interface Tactic {
  tactic?: string;
  request?: string;
  quote?: string;
  evidence?: string;
}
export interface JudgeFinding {
  mode: string;
  dimension: string;
  t_s: number | null;
  detector: string;
  hazard: boolean;
  evidence: string;
}
export interface JudgeSummary {
  x: number | null;
  fidelity: number | null;
  drift: number;
  misstatements: number;
  tactics: number;
  findings: number;
}
export interface JudgeCheckpoint {
  k: number;
  t_s: number | null;
  quality: { value: number | null; spread: number | null; samples: XSample[]; reason: string | null } | null;
  goals: {
    fidelity: number | null;
    inferred_goals: InferredGoal[];
    drift: DriftItem[];
    priority_inversions: Array<Record<string, unknown> | string>;
    reason: string | null;
  } | null;
  claims: { value: number | null; stages: ClaimStage[]; reason: string | null } | null;
  manipulation: { value: number | null; tactics: Tactic[]; reason: string | null } | null;
  findings: JudgeFinding[];
  judges: string[];
  cost_usd: number | null;
  summary: JudgeSummary;
}
export interface JudgesResponse {
  run_id: string;
  ingested: boolean;
  judge_model: string | null;
  checkpoints: JudgeCheckpoint[];
  reason?: string;
}

export const judgesApi = {
  get: (id: string, signal?: AbortSignal) => apiFetch<JudgesResponse>(`/runs/${encodeURIComponent(id)}/judges`, { signal }),
};

/** Metric names behind the judge summary on each checkpoint row (values only, from /checkpoints). */
export const JUDGE_METRICS = {
  x: "X",
  fidelity: "lrae.beh.gm.fidelity",
  drift: "lrae.beh.gm.drift_items",
  misstatements: "lrae.beh.dc.prose_misstatements",
  tactics: "lrae.beh.se.tactics",
} as const;
