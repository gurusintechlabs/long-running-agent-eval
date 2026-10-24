import type { PassRate, TestPoint, TestRow } from "../../../api";

export type RowItem = { type: "tier"; tier: string; count: number } | { type: "test"; test: TestRow };

const tierNum = (t: string | null) => {
  const n = Number(t);
  return Number.isFinite(n) && t !== "" && t != null ? n : Infinity;
};

export function tierLabel(t: string | null): string {
  return t == null || t === "" ? "untiered" : t;
}

/** Tests sorted by tier (numeric first) then id, with a header row per tier. */
export function buildRows(tests: TestRow[]): RowItem[] {
  const sorted = [...tests].sort((a, b) => tierNum(a.tier) - tierNum(b.tier) || tierLabel(a.tier).localeCompare(tierLabel(b.tier)) || a.id.localeCompare(b.id));
  const out: RowItem[] = [];
  let cur: string | undefined;
  let headerIdx = -1;
  for (const t of sorted) {
    const tl = tierLabel(t.tier);
    if (tl !== cur) {
      cur = tl;
      headerIdx = out.length;
      out.push({ type: "tier", tier: tl, count: 0 });
    }
    out.push({ type: "test", test: t });
    (out[headerIdx] as { count: number }).count++;
  }
  return out;
}

/** Column index of every pass->fail/error ("regression") and fail/error->pass ("recovery") in a cells string. */
export function cellFlips(cells: string): { col: number; kind: "regression" | "recovery" }[] {
  const out: { col: number; kind: "regression" | "recovery" }[] = [];
  let prev: string | null = null; // last scored outcome
  for (let i = 0; i < cells.length; i++) {
    const c = cells[i];
    if (c === "-" || c === "s") continue;
    const bad = c === "f" || c === "e";
    if (prev === "p" && bad) out.push({ col: i, kind: "regression" });
    else if (prev === "bad" && c === "p") out.push({ col: i, kind: "recovery" });
    prev = bad ? "bad" : c;
  }
  return out;
}

export interface StageBand {
  stage: number | null;
  from: number;
  to: number; // inclusive
}

/** Contiguous runs of points that belong to the same stage. */
export function stageBands(points: TestPoint[]): StageBand[] {
  const out: StageBand[] = [];
  points.forEach((p, i) => {
    const last = out[out.length - 1];
    if (last && last.stage === p.stage) last.to = i;
    else out.push({ stage: p.stage, from: i, to: i });
  });
  return out;
}

export const OUTCOME_LABEL: Record<string, string> = { p: "passed", f: "failed", e: "error", s: "skipped", "-": "not scored" };

export interface PassSeries {
  name: string;
  data: [number, number | null][];
}

/** Pass-rate series over time for the line chart: overall, established, then one per tier. */
export function passRateSeries(rates: PassRate[]): PassSeries[] {
  const out: PassSeries[] = [
    { name: "overall", data: rates.map((r) => [r.t_s ?? 0, r.overall]) },
    { name: "established", data: rates.map((r) => [r.t_s ?? 0, r.established]) },
  ];
  const tiers = new Set<string>();
  for (const r of rates) for (const t of Object.keys(r.tiers)) tiers.add(t);
  [...tiers].sort((a, b) => tierNum(a) - tierNum(b)).forEach((t) =>
    out.push({
      name: `tier ${t}`,
      data: rates.map((r) => {
        const v = r.tiers[t];
        return [r.t_s ?? 0, v && v[1] > 0 ? v[0] / v[1] : null];
      }),
    }),
  );
  return out.filter((s) => s.data.some((d) => d[1] != null));
}

/** Last point of each stage -> pass rates at the end of that stage. */
export function stageEndRates(rates: PassRate[]): { stage: number; overall: number | null; established: number | null }[] {
  const m = new Map<number, PassRate>();
  for (const r of rates) if (r.stage != null) m.set(r.stage, r);
  return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([stage, r]) => ({ stage, overall: r.overall, established: r.established }));
}
