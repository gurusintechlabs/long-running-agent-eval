// U3 data API: raw event log and normalised transcript (docs/ui-api-events.md §1-6).
// Everything the agent produced is untrusted text: render it with React text nodes only.
import { apiFetch } from "./client";
import { qs } from "./query";

const enc = encodeURIComponent;

export type EventSource = "agent_stream" | "otel" | "orchestrator" | "guardrail" | "counterpart" | "env" | "scorer";
export const EVENT_SOURCES: EventSource[] = ["agent_stream", "otel", "orchestrator", "guardrail", "counterpart", "env", "scorer"];

export interface LogEvent {
  /** Single-source cursor (`agent_stream:123`): usable with events/at. */
  cursor: string;
  source: string;
  ts: string | null;
  t_s: number | null;
  type: string;
  seq: number | null;
  bytes: number;
  truncated: boolean;
  payload: unknown;
}

export interface EventsResponse {
  run_id: string;
  mode: "single" | "merged";
  sources: string[];
  events: LogEvent[];
  next: string;
  eof: boolean;
  scan_capped: boolean;
  page_capped: boolean;
  limit: number;
}

export interface EventsParams {
  source?: string[];
  type?: string;
  q?: string;
  after?: string | null;
  limit?: number;
  max_chars?: number;
}

export interface EventsSummary {
  run_id: string;
  sources: Record<
    string,
    { bytes: number; lines: number; bad_lines: number; oversized_lines: number; first_ts: string | null; last_ts: string | null; counts: Record<string, number> }
  >;
  clocks: { start_epoch: number; offset_s: number }[];
}

interface ItemBase {
  cursor: string;
  seq: number | null;
  ts: string | null;
  t_s: number | null;
  turn: number | null;
}
export interface TextItem extends ItemBase {
  kind: "text";
  text: string;
  chars: number;
  text_truncated: boolean;
}
export interface ToolItem extends ItemBase {
  kind: "tool";
  tool: string | null;
  tool_use_id: string | null;
  input_summary: string;
  input_truncated: boolean;
  status: "ok" | "error" | "pending";
  dur_s: number | null;
  result_size: number | null;
  result_tail: string | null;
  has_result: boolean;
  result_cursor?: string | null;
}
export interface CompactionItem extends ItemBase {
  kind: "compaction";
  trigger: string | null;
  pre_tokens: number | null;
}
export interface TestRunItem extends ItemBase {
  kind: "test_run";
  passed: number | null;
  failed: number | null;
  errors: number | null;
  skipped: number | null;
  raw_summary: string | null;
}
export interface SessionItem extends ItemBase {
  kind: "session";
  event: string;
  session_id: string | null;
  model?: string | null;
  subtype?: string | null;
  is_error?: boolean | null;
  total_cost_usd?: number | null;
  num_turns?: number | null;
}
export interface DeniedItem extends ItemBase {
  kind: "denied";
  tool: string | null;
  input_summary: string;
}
export type TranscriptItem = TextItem | ToolItem | CompactionItem | TestRunItem | SessionItem | DeniedItem;

export interface TranscriptResponse {
  run_id: string;
  mode: "page" | "around";
  anchor: string | null;
  items: TranscriptItem[];
  next: string | null;
  eof: boolean;
  total_items: number;
  turns: { turn: number; start_s: number | null; end_s: number | null; first?: boolean; returncode?: number | null }[];
  tools: { tool: string | null; count: number; errors: number }[];
  indexed_bytes: number;
}

export interface TranscriptParams {
  after?: string | null;
  limit?: number;
  tool?: string[];
  kind?: string[];
  q?: string;
  errors_only?: boolean;
  turn?: number | null;
  around?: string | null;
  around_t_s?: number | null;
  before?: number;
  after_n?: number;
  max_chars?: number;
}

export interface TranscriptItemDetail {
  run_id: string;
  item: TranscriptItem;
  event: LogEvent | null;
  result_event: LogEvent | null;
  result_text: string | null;
  result_text_truncated: boolean;
}

export const eventsApi = {
  list: (id: string, p: EventsParams = {}, signal?: AbortSignal) =>
    apiFetch<EventsResponse>(
      `/runs/${enc(id)}/events${qs({ source: p.source?.join(","), type: p.type, q: p.q, after: p.after, limit: p.limit, max_chars: p.max_chars })}`,
      { signal },
    ),
  at: (id: string, cursor: string, signal?: AbortSignal) =>
    apiFetch<{ run_id: string; event: LogEvent }>(`/runs/${enc(id)}/events/at${qs({ cursor })}`, { signal }),
  summary: (id: string, signal?: AbortSignal) => apiFetch<EventsSummary>(`/runs/${enc(id)}/events/summary`, { signal }),
};

export const transcriptApi = {
  list: (id: string, p: TranscriptParams = {}, signal?: AbortSignal) =>
    apiFetch<TranscriptResponse>(
      `/runs/${enc(id)}/transcript${qs({
        after: p.after,
        limit: p.limit,
        tool: p.tool?.join(","),
        kind: p.kind?.join(","),
        q: p.q,
        errors_only: p.errors_only,
        turn: p.turn,
        around: p.around,
        around_t_s: p.around_t_s,
        before: p.before,
        after_n: p.after_n,
        max_chars: p.max_chars,
      })}`,
      { signal },
    ),
  item: (id: string, cursor: string, signal?: AbortSignal) =>
    apiFetch<TranscriptItemDetail>(`/runs/${enc(id)}/transcript/item${qs({ cursor })}`, { signal }),
};
