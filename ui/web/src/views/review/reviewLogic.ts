import type { ReviewCounts, ReviewDecisionRecord, ReviewItem } from "../../api";

export type StatusFilter = "pending" | "decided" | "confirm" | "reject" | "unsure" | "all";
export const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "decided", label: "Decided" },
  { value: "confirm", label: "Confirmed" },
  { value: "reject", label: "Rejected" },
  { value: "unsure", label: "Unsure" },
  { value: "all", label: "All" },
];

export interface ReviewFilters {
  status: StatusFilter;
  kind: string;
  group: string;
  name: string;
}

export const DEFAULT_FILTERS: ReviewFilters = { status: "pending", kind: "", group: "", name: "" };

export function matchesStatus(item: Pick<ReviewItem, "status">, s: StatusFilter): boolean {
  if (s === "all") return true;
  if (s === "decided") return item.status !== "pending";
  return item.status === s;
}

export function filterItems(items: ReviewItem[], f: ReviewFilters): ReviewItem[] {
  return items.filter(
    (i) => matchesStatus(i, f.status) && (!f.kind || i.kind === f.kind) && (!f.group || i.group === f.group) && (!f.name || i.name === f.name),
  );
}

export function countItems(items: ReviewItem[]): ReviewCounts {
  const c: ReviewCounts = { pending: 0, confirm: 0, reject: 0, unsure: 0 };
  for (const i of items) c[i.status] += 1;
  return c;
}

/** Latest decision wins; the history count grows (the log is append-only). */
export function applyDecisions(items: ReviewItem[], recs: ReviewDecisionRecord[]): ReviewItem[] {
  if (recs.length === 0) return items;
  const last = new Map<string, ReviewDecisionRecord>();
  const n = new Map<string, number>();
  for (const r of recs) {
    last.set(r.item_id, r);
    n.set(r.item_id, (n.get(r.item_id) ?? 0) + 1);
  }
  return items.map((i) => {
    const r = last.get(i.item_id);
    return r ? { ...i, decision: r, status: r.decision, history_count: i.history_count + (n.get(i.item_id) ?? 1) } : i;
  });
}

export function groupOptions(items: ReviewItem[]): { value: string; count: number }[] {
  const m = new Map<string, number>();
  for (const i of items) m.set(i.group, (m.get(i.group) ?? 0) + 1);
  return [...m].map(([value, count]) => ({ value, count })).sort((a, b) => a.value.localeCompare(b.value));
}

export function nameOptions(items: ReviewItem[], group: string): { value: string; count: number }[] {
  const m = new Map<string, number>();
  for (const i of items) if (!group || i.group === group) m.set(i.name, (m.get(i.name) ?? 0) + 1);
  return [...m].map(([value, count]) => ({ value, count })).sort((a, b) => a.value.localeCompare(b.value));
}

/** Link to the run's transcript at the item's position. The run-detail tab reads `k` and `t_s`. */
export function transcriptHref(i: ReviewItem): string {
  const q = new URLSearchParams({ tab: "transcript" });
  const cur = i.context?.cursor;
  const t = cur?.t_s ?? i.t_s;
  const k = cur?.k ?? i.k;
  if (t != null) q.set("t_s", String(Math.round(t * 1000) / 1000));
  if (k != null) q.set("k", String(k));
  return `/runs/${encodeURIComponent(i.run_id)}?${q}`;
}

export function formatClock(t: number | null | undefined): string {
  if (t == null || !Number.isFinite(t)) return "–";
  const s = Math.max(0, Math.round(t));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${p(m)}:${p(sec)}` : `${m}:${p(sec)}`;
}

export function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}
