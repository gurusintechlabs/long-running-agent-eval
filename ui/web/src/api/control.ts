// Run-control API (docs/ui-api-control.md). Kept in its own file so the shared client stays small.
import { ApiError, apiFetch } from "./client";

const enc = encodeURIComponent;

export interface ControlSpecEntry {
  name: string;
  source: "example" | "draft";
  editable: boolean;
  path: string;
  valid: boolean;
  spec_hash: string | null;
  errors: { path?: string; message?: string }[];
  experiment_id?: string | null;
  runtime?: string | null;
  model?: string | null;
  mtime?: number | null;
}

export interface Estimate {
  kind: "launch" | "resume";
  spec_path?: string;
  experiment_id?: string;
  spec_hash?: string;
  runtime?: string;
  model?: string | null;
  claude_code_version?: string | null;
  judge_runtime?: string | null;
  judge_model?: string | null;
  real_spend: boolean;
  spend_reasons?: string[];
  configs?: string[];
  repeats?: number[];
  run_ids?: string[];
  run_count?: number;
  per_run_usd?: number | null;
  per_run_tokens?: number | null;
  experiment_usd?: number | null;
  max_spend_usd?: number | null;
  spent_so_far_usd?: number | null;
  duration_min?: number | null;
  checkpoint_interval_min?: number | null;
  checkpoint_count?: number | null;
  max_wall_clock_min?: number | null;
  // resume only
  run_id?: string;
  from?: string;
  remaining_checkpoints?: number | null;
}

export interface PreflightCheck {
  name: string;
  ok: boolean;
  detail?: string;
}

export interface Confirmation {
  required: boolean;
  fields?: { confirm_usd: number; confirm_runs: number };
  message?: string;
}

export interface PreviewResponse {
  estimate: Estimate;
  checks: PreflightCheck[];
  conflicts: unknown[];
  blockers: unknown[];
  warnings: unknown[];
  launch_allowed_now: boolean;
  confirmation: Confirmation;
  confirmation_nonce: string | null;
  expires_in_s: number;
}

export interface LaunchResult {
  started: boolean;
  manifest_seen: boolean;
  pid: number;
  run_id?: string;
  run_ids?: string[];
  log?: string;
}

export interface ControlState {
  active: boolean;
  run: { run_id: string; pid: number; state: string; source: string; verified: boolean } | null;
  active_all: unknown[];
  launch_allowed: boolean;
  reason: string | null;
  job: { kind: string; pid: number; started_epoch: number; alive: boolean; exit_code: number | null; run_ids: string[] } | null;
  log_tail: string | null;
  pending_nonces: number;
}

export interface JobResult {
  started?: boolean;
  finished?: boolean;
  exit_code?: number | null;
  pid?: number;
  log?: string;
  output_tail?: string;
}

export interface SignalResult {
  signalled: string;
  pid: number;
  run_id: string;
  clean?: JobResult;
}

export interface LaunchRequest {
  spec_path: string;
  config?: string | string[];
  repeat?: number | number[];
}

export interface ConfirmTyped {
  confirm_usd?: number;
  confirm_runs?: number;
}

export const controlApi = {
  specs: (signal?: AbortSignal) => apiFetch<{ specs: ControlSpecEntry[] }>("/specs", { signal }),
  state: (signal?: AbortSignal) => apiFetch<ControlState>("/control/state", { signal }),
  launchPreview: (req: LaunchRequest) => apiFetch<PreviewResponse>("/launch/preview", { method: "POST", body: req }),
  launch: (nonce: string, typed: ConfirmTyped) =>
    apiFetch<LaunchResult>("/launch", { method: "POST", body: { nonce, ...typed } }),
  resumePreview: (id: string, from: string) =>
    apiFetch<PreviewResponse>(`/runs/${enc(id)}/resume/preview`, { method: "POST", body: { from } }),
  resume: (id: string, from: string, nonce: string, typed: ConfirmTyped) =>
    apiFetch<LaunchResult>(`/runs/${enc(id)}/resume`, { method: "POST", body: { from, nonce, ...typed } }),
  stop: (id: string) => apiFetch<SignalResult>(`/runs/${enc(id)}/stop`, { method: "POST", body: {} }),
  kill: (id: string, confirm: string) =>
    apiFetch<SignalResult>(`/runs/${enc(id)}/kill`, { method: "POST", body: { confirm } }),
  score: (id: string, checkpoint?: number) =>
    apiFetch<JobResult>(`/runs/${enc(id)}/score`, { method: "POST", body: checkpoint == null ? {} : { checkpoint } }),
  clean: () => apiFetch<JobResult>("/clean", { method: "POST", body: {} }),
};

/** Server error text and code. The control module answers {"detail": {"code", "message", ...}}; other errors have a string detail. */
export interface ErrInfo {
  status: number;
  code: string | null;
  message: string;
  extra: Record<string, unknown>;
}

export function errInfo(e: unknown): ErrInfo {
  if (e instanceof ApiError) {
    const body = e.body as { detail?: unknown } | null;
    const d = body && typeof body === "object" ? body.detail : undefined;
    if (d && typeof d === "object" && !Array.isArray(d)) {
      const o = d as Record<string, unknown>;
      return { status: e.status, code: typeof o.code === "string" ? o.code : null, message: typeof o.message === "string" ? o.message : e.message, extra: o };
    }
    if (Array.isArray(d)) {
      const msg = d.map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : String(x))).join("; ");
      return { status: e.status, code: null, message: msg || e.message, extra: {} };
    }
    return { status: e.status, code: null, message: e.message, extra: {} };
  }
  return { status: 0, code: null, message: e instanceof Error ? e.message : String(e), extra: {} };
}
