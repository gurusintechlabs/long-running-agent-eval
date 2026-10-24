// Label review API (docs/ui-api-specs.md section 4). Evidence and notes are untrusted: render as text only.
import { apiFetch } from "./client";

export type ReviewDecisionKind = "confirm" | "reject" | "unsure";
export type ReviewStatus = "pending" | ReviewDecisionKind;

export interface ReviewDecisionRecord {
  ts: string;
  run_id: string;
  item_id: string;
  decision: ReviewDecisionKind;
  note: string | null;
  reviewer: string | null;
}

export interface ReviewCursor {
  k?: number | null;
  t_s?: number | null;
  t_detected_s?: number | null;
}

export interface ReviewItem {
  run_id: string;
  item_id: string;
  source: string;
  kind: "hazard" | "behavior" | string;
  k: number | null;
  t_s: number | null;
  group: string;
  name: string;
  dimension?: string | null;
  hazard?: boolean;
  /** true = rule, false = judge, null = not applicable. */
  deterministic: boolean | null;
  title: string;
  evidence: string | null;
  context?: { pass_id?: string; ts?: string; cursor?: ReviewCursor } & Record<string, unknown>;
  proposed_label?: ReviewDecisionKind | null;
  draft_note?: string | null;
  decision: ReviewDecisionRecord | null;
  status: ReviewStatus;
  history_count: number;
}

export interface ReviewCounts {
  pending: number;
  confirm: number;
  reject: number;
  unsure: number;
}

export interface ReviewQueueResponse {
  items: ReviewItem[];
  total: number;
  offset: number;
  counts: ReviewCounts;
}

export interface ReviewRunEntry extends ReviewCounts {
  run_id: string;
  items: number;
}

export interface BatchEntry {
  item_id: string;
  decision: ReviewDecisionKind;
  note?: string | null;
}

const enc = encodeURIComponent;
export const REVIEW_PAGE = 500;
export const REVIEW_MAX_ITEMS = 5000;

export const reviewApi = {
  runs: (signal?: AbortSignal) => apiFetch<{ runs: ReviewRunEntry[] }>("/review/runs", { signal }),
  queue: (runId: string, opts: { status?: string; kind?: string; limit?: number; offset?: number } = {}, signal?: AbortSignal) => {
    const q = new URLSearchParams({ run_id: runId, status: opts.status ?? "all", limit: String(opts.limit ?? REVIEW_PAGE) });
    if (opts.kind) q.set("kind", opts.kind);
    if (opts.offset) q.set("offset", String(opts.offset));
    return apiFetch<ReviewQueueResponse>(`/review/queue?${q}`, { signal });
  },
  /** Every item of a run (all statuses), following pages up to REVIEW_MAX_ITEMS. */
  async queueAll(runId: string, signal?: AbortSignal): Promise<ReviewQueueResponse> {
    const first = await reviewApi.queue(runId, { offset: 0 }, signal);
    const items = [...first.items];
    while (items.length < first.total && items.length < REVIEW_MAX_ITEMS) {
      const page = await reviewApi.queue(runId, { offset: items.length }, signal);
      if (page.items.length === 0) break;
      items.push(...page.items);
    }
    return { ...first, items };
  },
  decide: (runId: string, itemId: string, decision: ReviewDecisionKind, note?: string | null) =>
    apiFetch<{ ok: boolean; decision: ReviewDecisionRecord }>("/review/decision", {
      method: "POST",
      body: { run_id: runId, item_id: itemId, decision, ...(note ? { note } : {}) },
    }),
  decideBatch: (runId: string, decisions: BatchEntry[]) =>
    apiFetch<{ ok: boolean; appended: number; decisions: ReviewDecisionRecord[] }>("/review/decisions", {
      method: "POST",
      body: { run_id: runId, decisions },
    }),
  history: (runId: string, itemId: string, signal?: AbortSignal) =>
    apiFetch<{ run_id: string; history: ReviewDecisionRecord[] }>(
      `/review/history?run_id=${enc(runId)}&item_id=${enc(itemId)}`,
      { signal },
    ),
};
