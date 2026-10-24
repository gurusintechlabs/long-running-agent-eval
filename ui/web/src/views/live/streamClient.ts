import { authState, getToken } from "../../api";
import { SseParser } from "./sse";
import type { DisplayEvent, StreamFrame } from "./types";

// Client for GET /api/runs/{id}/stream: fetch + ReadableStream (EventSource cannot send the token header).
// It reconnects on its own with the last cursor (Last-Event-ID header and ?from=), backs off, and watches
// the heartbeat. Everything it receives is data: frames are validated, unknown event names are ignored.

export type StreamStatus =
  | "connecting"
  | "open" // hello received
  | "reconnecting"
  | "ended" // run.ended, or a finite (follow=false) stream finished
  | "unauthorized"
  | "failed"; // 404 or another non-retryable answer

export interface StreamParams {
  from?: string; // tail | now | start | v1:cursor
  backlog?: number;
  sources?: string[];
  level?: "info" | "debug";
  fold?: boolean;
  follow?: boolean;
  heartbeat_s?: number;
}

export interface FollowOptions {
  runId: string;
  params?: StreamParams;
  signal: AbortSignal;
  onFrame: (f: StreamFrame) => void;
  onStatus?: (s: StreamStatus, info?: { attempt: number; retryInMs?: number; httpStatus?: number; message?: string }) => void;
  /** The server rejected our cursor (400): the caller should drop what it has; we restart from the tail. */
  onReset?: () => void;
  /** Backoff schedule in ms (last value repeats). */
  backoffMs?: number[];
  /** No bytes for this long = connection is dead: abort and reconnect. Default 3 x heartbeat. */
  watchdogMs?: number;
  /** Test hook. */
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
}

export const DEFAULT_BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];

const KNOWN = new Set(["hello", "ev", "caught-up", "heartbeat", "run.ending", "run.ended"]);

function sleepAbortable(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const t = setTimeout(done, ms);
    function done() {
      signal.removeEventListener("abort", done);
      clearTimeout(t);
      resolve();
    }
    signal.addEventListener("abort", done);
  });
}

function isDisplayEvent(d: unknown): d is DisplayEvent {
  if (!d || typeof d !== "object") return false;
  const o = d as Record<string, unknown>;
  return typeof o.id === "string" && typeof o.kind === "string" && typeof o.type === "string";
}

/** Turn one raw SSE frame into a typed frame, or null when it is malformed or unknown. */
export function toFrame(raw: { event: string; id: string | null; data: string }): StreamFrame | null {
  if (!KNOWN.has(raw.event)) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw.data);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  if (raw.event === "ev" && !isDisplayEvent(data)) return null;
  return { event: raw.event, id: raw.id, data } as StreamFrame;
}

export function buildStreamUrl(runId: string, p: StreamParams, cursor: string | null): string {
  const q = new URLSearchParams();
  q.set("from", cursor ?? p.from ?? "tail");
  if (!cursor && p.backlog != null) q.set("backlog", String(p.backlog));
  if (p.sources && p.sources.length) q.set("sources", p.sources.join(","));
  if (p.level) q.set("level", p.level);
  if (p.fold === false) q.set("fold", "false");
  if (p.follow === false) q.set("follow", "false");
  if (p.heartbeat_s != null) q.set("heartbeat_s", String(p.heartbeat_s));
  return `/api/runs/${encodeURIComponent(runId)}/stream?${q.toString()}`;
}

/** Resolves when the stream is finished for good (run ended, aborted, unauthorized or failed). */
export async function followStream(opts: FollowOptions): Promise<StreamStatus> {
  const { runId, signal } = opts;
  const params = opts.params ?? {};
  const backoff = opts.backoffMs ?? DEFAULT_BACKOFF_MS;
  const sleep = opts.sleep ?? sleepAbortable;
  let cursor: string | null = null;
  let attempt = 0;
  let heartbeatS = params.heartbeat_s ?? 10;
  const status = opts.onStatus ?? (() => {});

  while (!signal.aborted) {
    status(attempt === 0 ? "connecting" : "reconnecting", { attempt });
    const token = getToken();
    if (!token) {
      authState.setDenied(true);
      status("unauthorized", { attempt });
      return "unauthorized";
    }
    const headers: Record<string, string> = { "X-LRAE-Token": token, Accept: "text/event-stream" };
    if (cursor) headers["Last-Event-ID"] = cursor;

    const conn = new AbortController();
    const onAbort = () => conn.abort();
    signal.addEventListener("abort", onAbort);
    let watchdog: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      if (watchdog) clearTimeout(watchdog);
      watchdog = setTimeout(() => conn.abort(), opts.watchdogMs ?? Math.max(3 * heartbeatS * 1000, 1000));
    };

    let finished = false; // saw run.ended, or a finite stream ran to its end
    let opened = false;
    let httpStatus = 0;
    let message: string | undefined;
    try {
      arm();
      const res: Response = await fetch(buildStreamUrl(runId, params, cursor), { headers, signal: conn.signal });
      httpStatus = res.status;
      if (res.status === 401) {
        authState.setDenied(true);
        status("unauthorized", { attempt, httpStatus: 401 });
        return "unauthorized";
      }
      if (res.status === 400 && cursor) {
        // the log was replaced under our cursor: start over from the tail
        cursor = null;
        opts.onReset?.();
        continue;
      }
      if (res.status === 404 || (res.status >= 400 && res.status < 500 && res.status !== 429 && res.status !== 400)) {
        status("failed", { attempt, httpStatus: res.status });
        return "failed";
      }
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader: ReadableStreamDefaultReader<string> = res.body.pipeThrough(new TextDecoderStream()).getReader();
      const parser = new SseParser();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        arm();
        for (const raw of parser.push(value)) {
          const f = toFrame(raw);
          if (!f) continue;
          if (f.event === "hello") {
            opened = true;
            attempt = 0;
            if (typeof f.data.heartbeat_s === "number") heartbeatS = f.data.heartbeat_s;
            status("open", { attempt: 0 });
          }
          if (raw.id) cursor = raw.id;
          else if ((f.event === "heartbeat" || f.event === "caught-up") && typeof f.data.cursor === "string") cursor = f.data.cursor;
          opts.onFrame(f);
          if (f.event === "run.ended") finished = true;
        }
      }
      if (params.follow === false && opened) finished = true;
    } catch (e) {
      if (signal.aborted) return "ended";
      message = e instanceof Error ? e.message : String(e);
    } finally {
      if (watchdog) clearTimeout(watchdog);
      signal.removeEventListener("abort", onAbort);
    }
    if (signal.aborted) return "ended";
    if (finished) {
      status("ended", { attempt });
      return "ended";
    }
    // dropped, watchdog, 429 or 5xx: back off and resume from the last cursor
    const wait = backoff[Math.min(attempt, backoff.length - 1)] ?? 1000;
    attempt += 1;
    status("reconnecting", { attempt, retryInMs: wait, httpStatus: httpStatus || undefined, message });
    await sleep(wait, signal);
  }
  return "ended";
}
