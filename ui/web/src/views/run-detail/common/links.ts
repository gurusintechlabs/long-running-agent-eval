import type { TlBehavior, TlHazard, TlViolation } from "../../../api";

export const TABS = [
  { id: "overview", label: "Overview" },
  { id: "timeline", label: "Timeline" },
  { id: "tests", label: "Tests" },
  { id: "judges", label: "Judges" },
  { id: "transcript", label: "Transcript" },
  { id: "events", label: "Events" },
  { id: "checkpoints", label: "Checkpoints" },
] as const;
export type TabId = (typeof TABS)[number]["id"];

export function isTab(v: string | null): v is TabId {
  return TABS.some((t) => t.id === v);
}

type Extra = Record<string, string | number | null | undefined>;

/** `/runs/:id?tab=...&k=v`. Cursors are opaque server strings; they are URL-encoded, never interpreted. */
export function runTabUrl(runId: string, tab: TabId, extra: Extra = {}): string {
  const p = new URLSearchParams({ tab });
  for (const [k, v] of Object.entries(extra)) if (v != null && v !== "") p.set(k, String(v));
  return `/runs/${encodeURIComponent(runId)}?${p.toString()}`;
}

/** Deep link to the transcript window around a log position. Prefer a cursor, else run seconds. */
export function transcriptLink(runId: string, at: { cursor?: string | null; t_s?: number | null }): string | null {
  if (at.cursor) return runTabUrl(runId, "transcript", { cursor: at.cursor });
  if (at.t_s != null && Number.isFinite(at.t_s)) return runTabUrl(runId, "transcript", { t_s: Math.max(0, at.t_s) });
  return null;
}

export const violationLink = (runId: string, v: TlViolation) =>
  transcriptLink(runId, { cursor: v.stream_cursor, t_s: v.t_s });
export const behaviorLink = (runId: string, b: TlBehavior) => transcriptLink(runId, { t_s: b.t_s });
export const hazardLink = (runId: string, h: TlHazard) =>
  transcriptLink(runId, { t_s: h.t_detected_s ?? h.t_attributed_s });
