import type { RunSummary } from "../../api";

export interface RunFilters {
  search: string;
  state: string; // "" = any
  liveOnly: boolean;
  ingested: "" | "yes" | "no";
}

export const NO_FILTERS: RunFilters = { search: "", state: "", liveOnly: false, ingested: "" };

export function filterRuns(runs: RunSummary[], f: RunFilters): RunSummary[] {
  const q = f.search.trim().toLowerCase();
  return runs.filter((r) => {
    if (f.state && r.state !== f.state) return false;
    if (f.liveOnly && !r.live) return false;
    if (f.ingested === "yes" && !r.ingested) return false;
    if (f.ingested === "no" && r.ingested) return false;
    if (q) {
      const hay = [r.run_id, r.experiment_id, r.model, r.config, r.state, r.claude_code_version].filter(Boolean).join(" ").toLowerCase();
      if (!q.split(/\s+/).every((tok) => hay.includes(tok))) return false;
    }
    return true;
  });
}

/** Wall-clock duration: the ingested value, else end - start, else (live) elapsed so far. */
export function runDuration(r: RunSummary, nowEpoch = Date.now() / 1000): number | null {
  if (r.duration_s != null) return r.duration_s;
  if (r.start_epoch != null && r.end_epoch != null) return r.end_epoch - r.start_epoch;
  if (r.live && r.start_epoch != null) return nowEpoch - r.start_epoch;
  return null;
}

export function groupByExperiment(runs: RunSummary[], order: string[]): { id: string; runs: RunSummary[] }[] {
  const map = new Map<string, RunSummary[]>();
  for (const r of runs) {
    const id = r.experiment_id ?? "(unknown)";
    (map.get(id) ?? map.set(id, []).get(id)!).push(r);
  }
  const ids = [...map.keys()].sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    return (ia < 0 ? 1e9 : ia) - (ib < 0 ? 1e9 : ib);
  });
  return ids.map((id) => ({ id, runs: map.get(id)! }));
}
