// Shapes of the U4 live API (docs/ui-api-live.md). Only the fields the UI reads are typed; every text
// field is untrusted and must be rendered as a React text child.

export type Severity = "info" | "warning" | "violation" | "kill";

export type FeedKind =
  | "tool_call"
  | "tool_result"
  | "assistant_text"
  | "session"
  | "test_run"
  | "checkpoint"
  | "stage"
  | "turn"
  | "state"
  | "run"
  | "counterpart"
  | "env"
  | "budget"
  | "guardrail"
  | "kill"
  | "scorer"
  | "usage"
  | "raw"
  | "folded"
  | "generic";

export interface FoldInfo {
  group: string;
  pairs: number;
  open: boolean;
  total_paused_s?: number;
  typical_silence_s?: number;
  reasons?: Record<string, number>;
  first_cursor?: string;
  first_t_s?: number | null;
  last_cursor?: string;
  last_t_s?: number | null;
}

export interface DisplayEvent {
  id: string;
  cursor: string;
  ts: string | null;
  t_s: number | null;
  seq?: number | null;
  source: string;
  type: string;
  kind: FeedKind | string;
  title: string;
  summary: string;
  severity: Severity | string;
  level?: "info" | "debug" | string;
  pair: string | null;
  payload_preview: unknown;
  truncated?: boolean;
  fold: FoldInfo | null;
  raw_bytes?: number;
}

export interface FeedPage {
  events: DisplayEvent[];
  next_cursor?: string;
  at_end?: boolean;
  from?: string;
  count: number;
  source?: string;
  truncated?: boolean;
}

export interface StreamHello {
  run_id: string;
  mode: string;
  cursor: string;
  live: boolean;
  ended: boolean;
  heartbeat_s: number;
  level?: string;
}

export type StreamFrame =
  | { event: "hello"; id: string | null; data: StreamHello }
  | { event: "ev"; id: string | null; data: DisplayEvent }
  | { event: "caught-up"; id: string | null; data: { cursor: string; delivered: number } }
  | { event: "heartbeat"; id: string | null; data: { t?: number; cursor?: string; idle_s?: number } }
  | { event: "run.ending"; id: string | null; data: { state?: string; end?: unknown } }
  | {
      event: "run.ended";
      id: string | null;
      data: { state?: string; end?: unknown; scoring_complete?: boolean; crashed?: boolean; cursor?: string };
    };

export type Level = "ok" | "amber" | "red" | string;

export interface BudgetMeterData {
  per_run_usd: number | null;
  per_run_tokens: number | null;
  duration_min: number | null;
  usd_fraction: number | null;
  tokens_fraction: number | null;
  time_fraction: number | null;
  level: Level;
  time_level?: Level;
  thresholds?: { amber: number; red: number };
  burn_usd_per_min?: number | null;
  recent_usd_per_min?: number | null;
  cap_eta_s?: number | null;
  exhausted?: boolean;
  cost_usd?: number;
  tokens?: number;
}

export interface LiveSnapshot {
  run_id: string;
  as_of: number;
  live: boolean;
  ended: boolean;
  state: string | null;
  end: { state?: string; error?: string | null; censored_reason?: string | null } | null;
  harness_alive: boolean;
  catching_up: boolean;
  clock: {
    started: boolean;
    elapsed_s: number | null;
    duration_limit_s: number | null;
    remaining_s: number | null;
    fraction: number | null;
    resumed?: boolean;
  };
  checkpoints: {
    taken: number;
    planned: number | null;
    interval_s: number | null;
    last: { k: number; t_s: number | null; head_sha?: string | null; final?: string | null; cumulative_cost_usd?: number | null } | null;
    next: { k: number; t_s: number | null; due_in_s: number | null } | null;
    scoring: { queued: number; finished: number; in_flight: number[]; scored_ok: number };
  };
  stage: { current: number | null; delivered: number; last_t_s: number | null };
  turns: { started: number; ended: number; failed: number };
  cost: {
    usd: number | null;
    source: string;
    requests: number;
    api_errors: number;
    tokens: { total: number; input?: number; output?: number; cache_read?: number; cache_creation?: number };
  };
  context: { fill: number | null; max_fill: number | null; window: number | null; model: string | null; compactions: number };
  budget: BudgetMeterData;
  activity: {
    last_event_ts: string | null;
    last_event_age_s: number | null;
    idle_s: number | null;
    tool_calls: number;
    tool_errors: number;
    last_tool: { tool: string; ts: string } | null;
    test_runs: number;
    last_test_run: { passed: number; failed: number; errors: number } | null;
  };
  safety: { status: SafetyStatus; violations: number; warnings: number; kills: number };
  telemetry: { stalled: boolean; stall_pairs: number };
  scorer: { done: number; failed: number; hazards: number; behavior: number };
  interruptions?: unknown[];
  series?: { cost_usd: [number, number][]; context_fill: [number, number][] };
}

export type SafetyStatus = "clear" | "warnings" | "violations" | "killed";

export interface ContextWindow {
  source: string;
  center_ref: string;
  center_seq?: number;
  from_ref: string;
  to_ref: string;
  before: number;
  after: number;
  count: number;
  exact: boolean;
}

export interface KillInfo {
  rule_id: string;
  reason: string;
  detect_to_freeze_ms: number | null;
  reported_freeze_latency_ms?: number | null;
  target_ms?: number | null;
  within_target?: boolean | null;
  ts: string | null;
  t_s: number | null;
  cursor?: string;
  incident_id?: string | null;
  evidence?: string | null;
  evidence_highlight?: [number, number][];
  explanation?: string | null;
  context?: ContextWindow | null;
  run_state?: string | null;
  budget?: { cost_usd?: number; tokens?: number; per_run_usd?: number | null; per_run_tokens?: number | null } | null;
}

export interface Incident {
  id: string;
  cursor: string;
  ts: string | null;
  t_s: number | null;
  rule_id: string;
  title?: string;
  category?: string;
  severity: "warning" | "violation" | string;
  action: "log" | "kill" | string;
  channel: string;
  evidence: string | null;
  evidence_truncated?: boolean;
  evidence_highlight: [number, number][];
  explanation: string | null;
  why_it_matters?: string | null;
  killed: boolean;
  synthetic?: boolean;
  context: ContextWindow | null;
}

export interface IncidentGroup {
  rule_id: string;
  title?: string;
  category?: string;
  explanation?: string | null;
  count: number;
  severity: string;
  action: string;
  killed: boolean;
  channels: string[];
  first_t_s?: number | null;
  last_t_s?: number | null;
  sample_evidence?: string | null;
  incident_ids: string[];
}

export interface NoiseItem {
  kind: string;
  id: string;
  title: string;
  pairs: number;
  open: boolean;
  typical_silence_s?: number;
  total_paused_s?: number;
  explanation?: string;
}

export interface ScorerBehavior {
  cursor: string;
  k: number;
  mode: string;
  detector: string;
  t_s: number | null;
  hazard: boolean;
  dimension?: string;
  evidence?: string | null;
}

export interface ScorerHazard {
  cursor: string;
  k: number;
  dimension: string;
  rule: string;
  t_detected_s: number | null;
  evidence?: string | null;
}

export interface SafetyData {
  run_id: string;
  state: string | null;
  live: boolean;
  status: SafetyStatus;
  counts: { incidents: number; violations: number; warnings: number; kills: number };
  kill: KillInfo | null;
  kills?: KillInfo[];
  incidents: Incident[];
  incidents_total: number;
  incidents_truncated: boolean;
  groups: IncidentGroup[];
  noise: NoiseItem[];
  budget: { meter: BudgetMeterData | null; events?: unknown[] };
  scorer_signals?: {
    behavior: ScorerBehavior[];
    behavior_total: number;
    behavior_hazards: number;
    hazards: ScorerHazard[];
    hazards_total: number;
    note?: string;
  };
  policy?: { verified?: boolean | null; file?: string; note?: string | null };
  context_window?: { before: number; after: number };
}

export interface RuleDoc {
  rule_id: string;
  title: string;
  protects: string;
  why: string;
  category: string;
  source: string;
  policy: { section?: string; severity?: string | null; action?: string | null; scope?: string | null } | null;
}

export interface RulesResponse {
  policy: { source: string; file: string; sha256: string };
  rules: RuleDoc[];
}
