import { describe, expect, it } from "vitest";
import type { PassRate, TestPoint, TimelineResponse } from "../../api";
import { qs } from "../../api";
import { escapeHtml, formatClock } from "../../lib/text";
import timelineFx from "../../test/fixtures/timeline_haiku.json";
import { parseDiff } from "./checkpoints/diffParse";
import { behaviorLink, hazardLink, runTabUrl, transcriptLink, violationLink } from "./common/links";
import type { Palette } from "./common/colors";
import { buildRows, cellFlips, passRateSeries, stageBands, stageEndRates } from "./tests/heatmapModel";
import { layoutRows } from "./tests/HeatmapCanvas";
import { buildEvents, buildTimelineOption, clickLink, tooltipLines } from "./timeline/timelineModel";

const HOSTILE = "<img src=x onerror=alert(1)>";
const tl = timelineFx as unknown as TimelineResponse;
const pal: Palette = {
  text: "#000", muted: "#555", grid: "#eee", surface: "#fff", surface2: "#f4f4f4", border: "#ddd", accent: "#00f",
  ok: "#0a0", warn: "#a60", bad: "#a00", info: "#06a", neutral: "#444", series: ["#1", "#2", "#3", "#4", "#5", "#6", "#7"],
};

describe("links", () => {
  it("builds query strings and skips empties", () => {
    expect(qs({ a: 1, b: "x y", c: null, d: false, e: "" })).toBe("?a=1&b=x+y");
    expect(qs({})).toBe("");
  });
  it("deep-links to the transcript with the cursor the API returned, URL-encoded", () => {
    expect(transcriptLink("r1", { cursor: "agent_stream:385323", t_s: 9 })).toBe("/runs/r1?tab=transcript&cursor=agent_stream%3A385323");
    expect(transcriptLink("r1", { t_s: 12.5 })).toBe("/runs/r1?tab=transcript&t_s=12.5");
    expect(transcriptLink("r1", {})).toBeNull();
    expect(runTabUrl("a b", "checkpoints", { k: 3 })).toBe("/runs/a%20b?tab=checkpoints&k=3");
  });
  it("violations use stream_cursor, behaviour and hazards use run time", () => {
    const v = tl.guardrail.violations[0];
    expect(violationLink(tl.run_id, v)).toContain(`cursor=${encodeURIComponent(v.stream_cursor as string)}`);
    expect(behaviorLink(tl.run_id, tl.behavior[0])).toContain("t_s=");
    expect(hazardLink(tl.run_id, tl.hazards[0])).toContain("tab=transcript");
  });
});

describe("timeline model", () => {
  const events = buildEvents(tl);
  it("collects every lane into one sorted list", () => {
    const lanes = new Set(events.map((e) => e.lane));
    for (const l of ["Checkpoints", "Stages", "Compactions", "Hazards", "Behaviour", "Guardrail"]) expect(lanes.has(l as never)).toBe(true);
    expect([...events].sort((a, b) => a.t - b.t)).toEqual(events);
  });
  it("every guardrail violation marker deep-links to its stream cursor", () => {
    const g = events.filter((e) => e.lane === "Guardrail" && e.link?.includes("cursor="));
    expect(g.length).toBe(tl.guardrail.violations.filter((v) => v.stream_cursor).length);
  });
  it("builds a linked multi-grid option with zoom and a legend", () => {
    const o = buildTimelineOption(tl, pal, events) as unknown as {
      grid: unknown[]; dataZoom: { type: string; xAxisIndex: number[] }[]; legend: unknown; axisPointer: { link: unknown[] };
      series: { name: string; data: unknown[] }[];
    };
    expect(o.grid).toHaveLength(2);
    expect(o.dataZoom.map((z) => z.type)).toEqual(["inside", "slider"]);
    expect(o.dataZoom[0].xAxisIndex).toEqual([0, 1]);
    expect(o.axisPointer.link).toHaveLength(1);
    expect(o.legend).toBeTruthy();
    expect(o.series.map((s) => s.name)).toEqual(["Cumulative cost", "Context fill (max)", "Checkpoints", "Stages", "Compactions", "Hazards", "Behaviour", "Guardrail"]);
    expect(o.series[5].data).toHaveLength(tl.hazards.length);
  });
  it("click data carries the link", () => {
    expect(clickLink({ link: "/runs/x?tab=transcript" })).toBe("/runs/x?tab=transcript");
    expect(clickLink({ link: 3 })).toBeNull();
    expect(clickLink(undefined)).toBeNull();
  });
  it("tooltip text for hostile evidence is HTML-escaped by the formatter (UI-5)", () => {
    const bad = structuredClone(tl);
    bad.hazards[0].evidence = HOSTILE;
    bad.hazards[0].rule = HOSTILE;
    const ev = buildEvents(bad);
    const o = buildTimelineOption(bad, pal, ev) as unknown as { tooltip: { formatter: (p: unknown) => string } };
    const t = ev.find((e) => e.lane === "Hazards")!.t;
    const html = o.tooltip.formatter([{ axisValue: t }]);
    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<img");
    expect(tooltipLines(bad, ev, t, 5).join("\n")).toContain(HOSTILE); // raw lines are escaped only at the formatter
  });
  it("escapeHtml and formatClock", () => {
    expect(escapeHtml(`<a href="x">&'</a>`)).toBe("&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;");
    expect(formatClock(3725)).toBe("1:02:05");
    expect(formatClock(65)).toBe("1:05");
    expect(formatClock(null)).toBe("–");
  });
});

describe("heatmap model", () => {
  it("finds regressions and recoveries, ignoring skipped and unscored cells", () => {
    expect(cellFlips("ppfpp")).toEqual([{ col: 2, kind: "regression" }, { col: 3, kind: "recovery" }]);
    expect(cellFlips("p-sf")).toEqual([{ col: 3, kind: "regression" }]);
    expect(cellFlips("fffp")).toEqual([{ col: 3, kind: "recovery" }]);
    expect(cellFlips("pppp")).toEqual([]);
  });
  it("groups rows by numeric tier then id, with a header per tier", () => {
    const rows = buildRows([
      { id: "b", tier: "10", cells: "p" },
      { id: "z", tier: "2", cells: "p" },
      { id: "a", tier: "2", cells: "p" },
      { id: "u", tier: null, cells: "p" },
    ]);
    expect(rows.map((r) => (r.type === "tier" ? `T${r.tier}:${r.count}` : r.test.id))).toEqual(["T2:2", "a", "z", "T10:1", "b", "Tuntiered:1", "u"]);
  });
  it("sizes rows so thousands of tests stay drawable", () => {
    const many = Array.from({ length: 5000 }, (_, i) => ({ id: `t${i}`, tier: String(i % 20), cells: "p".repeat(60) }));
    const l = layoutRows(buildRows(many));
    expect(l.rowH).toBe(3);
    expect(l.total).toBeLessThan(5000 * 3 + 20 * 16 + 1);
  });
  it("merges points into stage bands", () => {
    const pts = [0, 0, 1, 1, 1, 2].map((s, i) => ({ idx: i, t_s: i, point: "commit", k: 1, sha: null, stage: s })) as TestPoint[];
    expect(stageBands(pts)).toEqual([{ stage: 0, from: 0, to: 1 }, { stage: 1, from: 2, to: 4 }, { stage: 2, from: 5, to: 5 }]);
  });
  it("derives per-tier and per-stage series", () => {
    const rates = [
      { t_s: 1, point: "commit", k: 1, stage: 0, passed: 1, active: 2, overall: 0.5, established: null, tiers: { "1": [1, 2], "2": [0, 0] } },
      { t_s: 2, point: "commit", k: 1, stage: 0, passed: 2, active: 2, overall: 1, established: 1, tiers: { "1": [2, 2] } },
      { t_s: 3, point: "commit", k: 2, stage: 1, passed: 1, active: 2, overall: 0.5, established: 0.5, tiers: {} },
    ] as PassRate[];
    const s = passRateSeries(rates);
    expect(s.map((x) => x.name)).toEqual(["overall", "established", "tier 1"]);
    expect(s[2].data).toEqual([[1, 0.5], [2, 1], [3, null]]);
    expect(stageEndRates(rates)).toEqual([{ stage: 0, overall: 1, established: 1 }, { stage: 1, overall: 0.5, established: 0.5 }]);
  });
});

describe("diff parser", () => {
  const diff = ["diff --git a/x.py b/x.py", "index 1..2 100644", "--- a/x.py", "+++ b/x.py", "@@ -3,3 +3,4 @@ def f():", " keep", "-old", "+new", "+<img src=x onerror=alert(1)>", " tail", "\\ No newline at end of file", "diff --git a/b.bin b/b.bin", "Binary files differ", ""].join("\n");
  it("numbers lines and counts additions and deletions", () => {
    const [f, b] = parseDiff(diff);
    expect(f.path).toBe("x.py");
    expect([f.added, f.deleted]).toEqual([2, 1]);
    const lines = f.lines.filter((l) => l.kind !== "meta" && l.kind !== "hunk");
    expect(lines.map((l) => [l.kind, l.oldNo, l.newNo])).toEqual([["ctx", 3, 3], ["del", 4, null], ["add", null, 4], ["add", null, 5], ["ctx", 5, 6]]);
    expect(b.binary).toBe(true);
  });
  it("handles an empty diff", () => {
    expect(parseDiff("")).toEqual([]);
  });
});
