import { getToken } from "./token";
import type {
  CheckpointsResponse,
  ExperimentsResponse,
  IngestResult,
  IngestStatus,
  RunDetail,
  RunsResponse,
} from "./types";

/** The server answered 401 (or we have no token): the user must open the URL printed by `lrae ui`. */
export class ApiAuthError extends Error {
  constructor(message = "missing or wrong token") {
    super(message);
    this.name = "ApiAuthError";
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Auth state shared with the UI: flipped to "denied" by any 401. */
type AuthListener = () => void;
let denied = false;
const listeners = new Set<AuthListener>();

export const authState = {
  isDenied: () => denied,
  setDenied(v: boolean) {
    if (denied === v) return;
    denied = v;
    listeners.forEach((l) => l());
  },
  subscribe(l: AuthListener) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
};

export interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  signal?: AbortSignal;
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const d = (body as Record<string, unknown>).detail ?? (body as Record<string, unknown>).output;
    if (typeof d === "string") return d;
  }
  return fallback;
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const token = getToken();
  if (!token) {
    authState.setDenied(true);
    throw new ApiAuthError("no token: open the URL printed by lrae ui");
  }
  const headers: Record<string, string> = { "X-LRAE-Token": token, Accept: "application/json" };
  let body: string | undefined;
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method: opts.method ?? "GET", headers, body, signal: opts.signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "cannot reach the lrae ui server (is it still running?)");
  }
  if (res.status === 401) {
    authState.setDenied(true);
    throw new ApiAuthError();
  }
  let parsed: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!res.ok) throw new ApiError(res.status, detailOf(parsed, `HTTP ${res.status}`), parsed);
  return parsed as T;
}

const enc = encodeURIComponent;

export const api = {
  health: (signal?: AbortSignal) => apiFetch<{ ok: boolean; version: string }>("/health", { signal }),
  runs: (signal?: AbortSignal) => apiFetch<RunsResponse>("/runs", { signal }),
  experiments: (signal?: AbortSignal) => apiFetch<ExperimentsResponse>("/experiments", { signal }),
  run: (id: string, signal?: AbortSignal) => apiFetch<RunDetail>(`/runs/${enc(id)}`, { signal }),
  checkpoints: (id: string, signal?: AbortSignal) =>
    apiFetch<CheckpointsResponse>(`/runs/${enc(id)}/checkpoints`, { signal }),
  ingestStatus: (signal?: AbortSignal) => apiFetch<IngestStatus>("/ingest/status", { signal }),
  /** The server answers 500 with {ok:false, output} when ingest fails: we surface that as a result, not a throw. */
  async ingest(): Promise<IngestResult> {
    try {
      return await apiFetch<IngestResult>("/ingest", { method: "POST", body: {} });
    } catch (e) {
      if (e instanceof ApiError && e.body && typeof e.body === "object" && "output" in e.body) {
        return { ok: false, output: String((e.body as { output: unknown }).output) };
      }
      throw e;
    }
  },
};
