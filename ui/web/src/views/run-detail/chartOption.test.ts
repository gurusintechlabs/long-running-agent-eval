import { describe, expect, it } from "vitest";
import type { CheckpointRow, Hazard } from "../../api";
import { availableMetrics, seriesFor } from "../../lib/metrics";
import { fx } from "../../test/helpers";
import { buildOption } from "./MetricCharts";

const theme = { text: "#000", muted: "#555", grid: "#eee", surface: "#fff", border: "#ddd", series: ["#123"] };
const cps = fx.checkpointsEarly.checkpoints as CheckpointRow[];

describe("metric series", () => {
  it("orders core metrics first, then the rest", () => {
    const m = availableMetrics(cps);
    expect(m.slice(0, 7)).toEqual(["P", "R", "D", "C", "W", "X", "S"]);
    expect(m).toContain("tokens_per_commit");
  });
  it("turns checkpoints into [minutes, value] points and skips missing values", () => {
    expect(seriesFor(cps, "P")[0]).toEqual([cps[0].t_s! / 60, 0.7]);
    expect(seriesFor(cps, "nope")).toEqual([]);
  });
  it("builds a line option with hazard markers and no custom (HTML) tooltip formatter", () => {
    const hz = fx.runEarly.hazards as Hazard[];
    const o = buildOption("P", cps, hz, theme, "#123") as { series: { data: unknown[]; markLine: { data: unknown[] } }[]; tooltip: Record<string, unknown> };
    expect(o.series[0].data).toHaveLength(cps.length);
    expect(o.series[0].markLine.data).toHaveLength(hz.length);
    expect(o.tooltip.formatter).toBeUndefined();
  });
});
