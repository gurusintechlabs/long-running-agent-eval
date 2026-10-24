import type { DisplayEvent } from "./types";

// In-memory feed buffer: time-ordered, replace-by-id (folded rows are re-sent with the same id), bounded
// (the oldest events are dropped once `cap` is exceeded) so a multi-hour run cannot grow without limit.

export const DEFAULT_CAP = 4000;

export interface FeedState {
  events: DisplayEvent[];
  /** ids currently in `events` (mutated in place: it is private bookkeeping, never rendered). */
  ids: Set<string>;
  /** Events dropped from the top because of the cap. */
  dropped: number;
  /** Events ever accepted (new ids only). */
  accepted: number;
}

export function emptyFeed(): FeedState {
  return { events: [], ids: new Set(), dropped: 0, accepted: 0 };
}

function isFoldRow(e: DisplayEvent): boolean {
  return e.kind === "folded" || e.id.startsWith("fold:");
}

function before(a: DisplayEvent, b: DisplayEvent): boolean {
  // strict "a sorts before b"; ISO timestamps compare as strings, missing ts keeps arrival order
  return a.ts != null && b.ts != null && a.ts < b.ts;
}

/** Add a batch. Returns a new state object (the events array is copied; the unchanged objects are shared). */
export function applyEvents(state: FeedState, incoming: DisplayEvent[], cap = DEFAULT_CAP): FeedState {
  if (incoming.length === 0) return state;
  const events = state.events.slice();
  const ids = state.ids;
  let accepted = state.accepted;
  for (const ev of incoming) {
    if (ids.has(ev.id)) {
      // replace in place: folded rows move nowhere, duplicates after a reconnect are harmless
      let i = events.length - 1;
      while (i >= 0 && events[i].id !== ev.id) i--;
      if (i >= 0) {
        events[i] = ev;
        continue;
      }
    }
    ids.add(ev.id);
    accepted++;
    const last = events[events.length - 1];
    if (!last || !before(ev, last) || isFoldRow(ev)) {
      events.push(ev);
    } else {
      // a late line from another log file: binary-search its slot (upper bound by ts)
      let lo = 0;
      let hi = events.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (before(ev, events[mid])) hi = mid;
        else lo = mid + 1;
      }
      events.splice(lo, 0, ev);
    }
  }
  let dropped = state.dropped;
  if (events.length > cap) {
    const n = events.length - cap;
    for (let i = 0; i < n; i++) ids.delete(events[i].id);
    events.splice(0, n);
    dropped += n;
  }
  return { events, ids, dropped, accepted };
}

// ---------------------------------------------------------------------------------------------------
// Rows (what the list draws): tool results are merged into their call, filters applied.

export interface FeedRow {
  key: string;
  ev: DisplayEvent;
  /** The matching tool.result, when it is in the buffer. */
  result?: DisplayEvent;
}

export type MinSeverity = "all" | "warning" | "violation";

export interface FeedFilters {
  /** Sources switched off with the chips (a kill row is always shown). */
  hidden: ReadonlySet<string>;
  minSeverity: MinSeverity;
  search: string;
}

const SEV_RANK: Record<string, number> = { info: 0, warning: 1, violation: 2, kill: 3 };
export function sevRank(s: string): number {
  return SEV_RANK[s] ?? 0;
}

const hayCache = new WeakMap<DisplayEvent, string>();
export function haystack(e: DisplayEvent): string {
  let h = hayCache.get(e);
  if (h === undefined) {
    let p: string;
    try {
      p = JSON.stringify(e.payload_preview) ?? "";
    } catch {
      p = "";
    }
    h = `${e.title}\n${e.summary}\n${e.type}\n${p.slice(0, 4000)}`.toLowerCase();
    hayCache.set(e, h);
  }
  return h;
}

export function rowSeverity(r: FeedRow): string {
  const a = r.ev.severity;
  const b = r.result?.severity;
  return b && sevRank(b) > sevRank(a) ? b : a;
}

export function buildRows(events: readonly DisplayEvent[], f: FeedFilters): FeedRow[] {
  const results = new Map<string, DisplayEvent>();
  const calls = new Set<string>();
  for (const e of events) {
    if (!e.pair) continue;
    if (e.kind === "tool_result") results.set(e.pair, e);
    else if (e.kind === "tool_call") calls.add(e.pair);
  }
  const q = f.search.trim().toLowerCase();
  const min = f.minSeverity === "all" ? 0 : f.minSeverity === "warning" ? 1 : 2;
  const rows: FeedRow[] = [];
  for (const e of events) {
    if (f.hidden.has(e.source) && e.kind !== "kill") continue;
    let row: FeedRow;
    if (e.kind === "tool_result" && e.pair && calls.has(e.pair)) continue; // merged into its call
    if (e.kind === "tool_call" && e.pair && results.has(e.pair)) row = { key: e.id, ev: e, result: results.get(e.pair) };
    else row = { key: e.id, ev: e };
    if (sevRank(rowSeverity(row)) < min) continue;
    if (q && !haystack(e).includes(q) && !(row.result && haystack(row.result).includes(q))) continue;
    rows.push(row);
  }
  return rows;
}

export function countBySource(events: readonly DisplayEvent[]): Record<string, number> {
  const c: Record<string, number> = {};
  for (const e of events) c[e.source] = (c[e.source] ?? 0) + 1;
  return c;
}
