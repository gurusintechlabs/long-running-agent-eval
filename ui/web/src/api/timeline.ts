// U3 data API: run timeline and checkpoint git/scorer views (docs/ui-api-events.md §8-10).
import { apiFetch } from "./client";
import { qs } from "./query";

const enc = encodeURIComponent;

export interface TlCheckpoint {
  cursor: string;
  k: number;
  t_s: number | null;
  head_sha: string | null;
  dirty: boolean | null;
  pause_ms: number | null;
  final: boolean | null;
  cumulative_cost_usd: number | null;
}
export interface TlViolation {
  cursor: string;
  type: string;
  t_s: number | null;
  rule_id: string;
  severity: string;
  action: string;
  channel: string | null;
  evidence: string | null;
  stream_seq?: number | null;
  stream_cursor?: string | null;
}
export interface TlBehavior {
  k: number | null;
  mode: string | null;
  dimension: string | null;
  t_s: number | null;
  detector: string;
  severity: string;
  hazard: boolean;
  deterministic: boolean;
  evidence: string | null;
}
export interface TlHazard {
  dimension: string;
  rule: string;
  k: number | null;
  t_attributed_s: number | null;
  t_detected_s: number | null;
  evidence: string | null;
}
export interface TlSeriesPoint {
  k: number;
  t_s: number | null;
  cost_usd: number | null;
  cum_cost_usd: number | null;
  context_fill_max: number | null;
  context_fill_last: number | null;
  compactions: number | null;
  tool_calls: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
}
export interface TimelineResponse {
  run_id: string;
  source_of_counters: "store" | "logs" | "none";
  end: Record<string, unknown> | null;
  last_checkpoint_t_s: number | null;
  checkpoints: TlCheckpoint[];
  stages: { cursor: string; stage: number; t_s: number | null; kind: string; interrupted: boolean }[];
  markers: { t_s: number | null; kind: string; label: string }[];
  states: { cursor: string; t_s: number | null; from: string; to: string }[];
  turns: { turn: number; start_s: number | null; end_s: number | null; first?: boolean; returncode?: number | null }[];
  hazards: TlHazard[];
  behavior: TlBehavior[];
  behavior_total: number;
  compactions: { cursor: string; t_s: number | null; trigger: string | null; pre_tokens: number | null }[];
  guardrail: {
    status: "clear" | "warnings" | "violations" | "killed" | string;
    violations: TlViolation[];
    violations_total: number;
    by_rule: { rule_id: string; count: number; severity: string; action: string; kills: number }[];
    kill: { cursor: string; t_s: number | null; rule_id: string; reason: string | null; freeze_latency_ms: number | null; detect_to_freeze_ms: number | null } | null;
    budget: { cursor: string; t_s: number | null; cost_usd: number | null; tokens: number | null; per_run_usd: number | null; per_run_tokens?: number | null } | null;
    telemetry_stalls: { count: number; resumed: number; first_t_s: number | null; gaps: { t_s: number | null; paused_s: number | null }[] } | null;
  };
  series: TlSeriesPoint[];
}

export interface DiffResponse {
  run_id: string;
  k: number;
  head: string | null;
  dirty: boolean | null;
  base: string | null;
  base_kind: "previous_checkpoint" | "seed" | "root" | "param" | string | null;
  available: boolean;
  reason: string | null;
  commits: { sha: string; parents: string[]; date: string | null; author: string | null; subject: string }[];
  commits_truncated: boolean;
  files: { path: string; added: number; deleted: number; binary: boolean }[];
  files_truncated: boolean;
  diff: string;
  diff_truncated: boolean;
}
export interface ScorerLogResponse {
  run_id: string;
  k: number;
  size: number;
  truncated: boolean;
  text: string;
}

export const timelineApi = {
  get: (id: string, signal?: AbortSignal) => apiFetch<TimelineResponse>(`/runs/${enc(id)}/timeline`, { signal }),
  diff: (id: string, k: number, p: { max_bytes?: number } = {}, signal?: AbortSignal) =>
    apiFetch<DiffResponse>(`/runs/${enc(id)}/checkpoints/${k}/diff${qs({ max_bytes: p.max_bytes })}`, { signal }),
  scorerLog: (id: string, k: number, signal?: AbortSignal) =>
    apiFetch<ScorerLogResponse>(`/runs/${enc(id)}/checkpoints/${k}/scorer-log`, { signal }),
};
