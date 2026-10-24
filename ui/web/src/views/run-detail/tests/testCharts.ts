import type { PassRate } from "../../../api";
import { formatClock } from "../../../lib/text";
import type { Palette } from "../common/colors";
import { passRateSeries, stageEndRates } from "./heatmapModel";

const pct = (v: unknown) => (typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "–");

const base = (p: Palette) => ({
  animation: false,
  textStyle: { color: p.muted },
  grid: { left: 46, right: 14, top: 36, bottom: 28 },
  legend: { top: 0, left: 0, textStyle: { color: p.text }, itemWidth: 14, itemHeight: 8, type: "scroll" },
  // Default tooltip formatter on purpose (it escapes names): series names here are fixed strings anyway.
  tooltip: { trigger: "axis", confine: true, backgroundColor: p.surface, borderColor: p.border, textStyle: { color: p.text }, valueFormatter: pct },
});

/** Pass rate over time: overall, established and one line per tier. */
export function passRateOption(rates: PassRate[], p: Palette) {
  const series = passRateSeries(rates);
  return {
    ...base(p),
    color: [p.text, p.accent, ...p.series],
    xAxis: { type: "value", min: "dataMin", max: "dataMax", axisLabel: { color: p.muted, formatter: (v: number) => formatClock(v) }, axisLine: { lineStyle: { color: p.grid } }, splitLine: { show: false } },
    yAxis: { type: "value", min: 0, max: 1, axisLabel: { color: p.muted, formatter: (v: number) => `${Math.round(v * 100)}%` }, splitLine: { lineStyle: { color: p.grid } } },
    series: series.map((s, i) => ({
      name: s.name,
      type: "line",
      data: s.data,
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: i < 2 ? 2.6 : 1.6, type: s.name === "established" ? "dashed" : "solid" },
    })),
  };
}

/** Pass rate at the end of each stage. */
export function stageOption(rates: PassRate[], p: Palette) {
  const rows = stageEndRates(rates);
  return {
    ...base(p),
    color: [p.series[0], p.series[2]],
    xAxis: { type: "category", data: rows.map((r) => `s${r.stage}`), axisLabel: { color: p.muted }, axisLine: { lineStyle: { color: p.grid } } },
    yAxis: { type: "value", min: 0, max: 1, axisLabel: { color: p.muted, formatter: (v: number) => `${Math.round(v * 100)}%` }, splitLine: { lineStyle: { color: p.grid } } },
    series: [
      { name: "overall", type: "bar", data: rows.map((r) => r.overall), barMaxWidth: 22 },
      { name: "established", type: "bar", data: rows.map((r) => r.established), barMaxWidth: 22 },
    ],
  };
}
