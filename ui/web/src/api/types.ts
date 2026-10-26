// JSON shapes returned by ui_server (see ui_server/store.py). Keep in sync with the server.

/** One run, as listed by GET /api/runs and returned inside GET /api/runs/{id}. */
export interface RunSummary {
  run_id: string;
  experiment_id: string | null;
  config: string | null;
  repeat: number | null;
  model: string | null;
  claude_code_version: string | null;
  isolation_mode: string | null;
  runtime: string | null;
  /** COMPLETED, BUDGET_EXHAUSTED, KILLED, INTERRUPTED, UNFINISHED, or the live orchestrator state. */
  state: string | null;
  live: boolean;
  resumed: boolean;
  start_epoch: number | null;
  end_epoch: number | null;
  checkpoints: number;
  /** Estimated, API-equivalent cost (D-16): not a bill. */
  cost_usd: number | null;
  tokens: number | null;
  ingested: boolean;
  /** The next four are null until the run is ingested into metrics.sqlite. */
  duration_s: number | null;
  ttfh_s: number | null;
  hazard_count: number | null;
  censored_reason: string | null;
}

export interface RunsResponse {
  runs: RunSummary[];
}

export interface ExperimentGroup {
  experiment_id: string;
  runs: number;
  states: Record<string, number>;
  cost_usd: number;
  last_start_epoch: number | null;
  live: boolean;
}

export interface ExperimentsResponse {
  experiments: ExperimentGroup[];
}

export interface RunEnd {
  state?: string | null;
  end_epoch?: number | null;
  end_reason?: string | null;
  censored_reason?: string | null;
  error?: string | null;
  checkpoints?: number | null;
  cost_usd?: number | null;
  tokens?: number | null;
}

/** The manifest subset the server exposes (MANIFEST_KEYS). `spec` is the parsed experiment spec. */
export interface RunManifest {
  run_id?: string;
  experiment_id?: string;
  config?: string;
  repeat?: number;
  model?: string;
  runtime?: string;
  spec_hash?: string;
  claude_code_version?: string;
  seed_commit?: string;
  isolation_mode?: string;
  /** Real manifests carry `{enabled, reason}`; older ones may lack it. */
  safe_mode?: { enabled?: boolean; reason?: string } | boolean | null;
  framework?: { dirty?: boolean; git_sha?: string };
  host?: { machine?: string; os?: string; python?: string };
  policy_sha256?: string;
  resumed?: boolean;
  start_epoch?: number;
  end?: RunEnd | null;
  spec?: Record<string, unknown>;
}

export interface Hazard {
  dimension: string;
  rule: string;
  t_attributed_s: number | null;
  t_detected_s: number | null;
  k: number | null;
  evidence: string | null;
}

export interface RunDetail {
  run: RunSummary;
  manifest: RunManifest;
  hazards: Hazard[];
}

export interface CheckpointRow {
  k: number;
  t_s: number | null;
  head_sha: string | null;
  dirty: boolean | null;
  pause_ms: number | null;
  /** Empty until the run is ingested. Names: P, R, D, C, W, X, S plus derived series. */
  metrics: Record<string, number>;
}

export interface CheckpointsResponse {
  run_id: string;
  ingested: boolean;
  checkpoints: CheckpointRow[];
}

export interface IngestStatus {
  store_exists: boolean;
  stale: boolean;
  reason: string | null;
  runs_on_disk: number;
  runs_in_store: number;
  missing_from_store: string[];
  store_epoch: number | null;
  newest_log_epoch: number | null;
}

export interface IngestResult {
  ok: boolean;
  output: string;
}
