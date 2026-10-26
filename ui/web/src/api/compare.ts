// Compare, survival and reports API (docs/ui-api-compare.md). Own file so the shared client stays small.
import { ApiAuthError, ApiError, apiFetch, authState } from "./client";
import { getToken } from "./token";
import type { Hazard, IngestStatus, RunSummary } from "./types";

const enc = encodeURIComponent;

export interface SeriesPoints {
  k: number[];
  t_s: (number | null)[];
  value: (number | null)[];
}

export interface CompareRun {
  run_id: string;
  summary: RunSummary;
  ingested: boolean;
  checkpoints: { k: number; t_s: number | null }[];
  /** Metric name -> series. Empty for runs that are not ingested. */
  series: Record<string, SeriesPoints>;
  /** cum_cost_usd, cost_usd, context_fill_max, compactions (those the store has). */
  counters: Record<string, SeriesPoints>;
  hazards: Hazard[];
}

export interface MetricDelta {
  metric: string;
  final: Record<string, number | null>;
  mean: Record<string, number | null>;
  min: Record<string, number | null>;
  max: Record<string, number | null>;
  delta_vs_base: Record<string, number | null>;
}

export interface SummaryDelta {
  field: string;
  values: Record<string, number | null>;
  delta_vs_base: Record<string, number | null>;
}

export interface CompareResponse {
  run_ids: string[];
  base: string;
  runs: CompareRun[];
  metrics: string[];
  aligned_by_k: Record<string, { k: number[]; values: Record<string, (number | null)[] | null> }>;
  metric_deltas: MetricDelta[];
  summary_deltas: SummaryDelta[];
  not_ingested: string[];
  notes: string[];
  cost_note: string;
}

export interface KmCurve {
  times: number[];
  surv: number[];
  lower: (number | null)[];
  upper: (number | null)[];
  n_risk: number[];
  n_event: number[];
  censor_times: number[];
  censor_surv: number[];
}

export interface SurvivalGroup {
  task_class: string;
  config: string;
  label: string;
  n: number;
  events: number;
  censored: number;
  censored_by_reason: Record<string, number>;
  available: boolean;
  km?: KmCurve;
  median_s?: number | null;
  median_text?: string;
  median_ci_boot_s?: [number | null, number | null];
  median_ci_hi_not_reached?: boolean;
  headline_s?: number | null;
  headline_available: boolean;
  headline_text: string;
  error?: string;
}

export interface SurvivalResponse {
  experiment: string;
  dimension: string | null;
  groups: SurvivalGroup[];
  excluded: Record<string, number>;
  runs_total: number;
  target: number;
  level: number;
  note: string | null;
}

export interface ReportArtifact {
  name: string;
  bytes: number;
  mtime: number;
}

export interface ReportEntry {
  experiment_id: string;
  in_store: boolean;
  has_reports: boolean;
  dashboard: ReportArtifact | null;
  pdf: ReportArtifact | null;
  figures: ReportArtifact[];
  built_epoch: number | null;
  older_than_store: boolean;
}

export interface ReportsResponse {
  experiments: ReportEntry[];
  ingest: IngestStatus;
  chrome: { available: boolean; error: string | null };
  cost_note: string;
}

export interface RebuildResult {
  ok: boolean;
  kind: "dashboard" | "pdf";
  exit_code: number | null;
  output: string;
  artifact: ReportArtifact | null;
  duration_s: number;
  stale_store: boolean;
}

/** GET a report artifact with the token header (an <img>/<iframe> src cannot send one). */
async function fetchFile(experiment: string, name: string): Promise<Response> {
  const token = getToken();
  if (!token) {
    authState.setDenied(true);
    throw new ApiAuthError("no token: open the URL printed by lrae ui");
  }
  const res = await fetch(`/api/reports/${enc(experiment)}/file?name=${enc(name)}`, { headers: { "X-LRAE-Token": token } });
  if (res.status === 401) {
    authState.setDenied(true);
    throw new ApiAuthError();
  }
  if (!res.ok) throw new ApiError(res.status, `${name}: HTTP ${res.status}`);
  return res;
}

export const compareApi = {
  compare: (ids: string[], signal?: AbortSignal) => apiFetch<CompareResponse>(`/compare?runs=${enc(ids.join(","))}`, { signal }),
  survival: (experiment: string, config?: string[], signal?: AbortSignal) =>
    apiFetch<SurvivalResponse>(`/survival?experiment=${enc(experiment)}${config?.length ? `&config=${enc(config.join(","))}` : ""}`, { signal }),
  reports: (signal?: AbortSignal) => apiFetch<ReportsResponse>("/reports", { signal }),
  rebuild: (experiment: string, kind: "dashboard" | "pdf", allowStale = false) =>
    apiFetch<RebuildResult>(`/reports/${enc(experiment)}/rebuild`, { method: "POST", body: { kind, allow_stale: allowStale } }),
  fileBlob: async (experiment: string, name: string): Promise<Blob> => (await fetchFile(experiment, name)).blob(),
  fileText: async (experiment: string, name: string): Promise<string> => (await fetchFile(experiment, name)).text(),
};
