import { apiFetch } from "../../api";
import type { DisplayEvent, FeedPage, LiveSnapshot, RulesResponse, SafetyData } from "./types";

const enc = encodeURIComponent;

export const liveApi = {
  live: (runId: string, signal?: AbortSignal) => apiFetch<LiveSnapshot>(`/runs/${enc(runId)}/live`, { signal }),
  safety: (runId: string, signal?: AbortSignal) => apiFetch<SafetyData>(`/runs/${enc(runId)}/safety?limit=200`, { signal }),
  rules: (signal?: AbortSignal) => apiFetch<RulesResponse>("/rules", { signal }),
  feedPage: (runId: string, q: { from: string; limit?: number; level?: string }, signal?: AbortSignal) => {
    const p = new URLSearchParams({ from: q.from, limit: String(q.limit ?? 500) });
    if (q.level) p.set("level", q.level);
    return apiFetch<FeedPage>(`/runs/${enc(runId)}/feed?${p.toString()}`, { signal });
  },
  feedRange: (runId: string, refFrom: string, refTo: string, signal?: AbortSignal) =>
    apiFetch<FeedPage>(`/runs/${enc(runId)}/feed?ref_from=${enc(refFrom)}&ref_to=${enc(refTo)}`, { signal }),
  feedEvent: (runId: string, ref: string, signal?: AbortSignal) =>
    apiFetch<DisplayEvent>(`/runs/${enc(runId)}/feed/event?ref=${enc(ref)}`, { signal }),
};

/** Where a ref should open in the run-detail transcript tab. */
export function transcriptLink(runId: string, ref: string): string {
  return `/runs/${enc(runId)}?tab=transcript&cursor=${enc(ref)}`;
}
