import type { ChartTheme } from "../../components/chart/theme";

// ECharts options for the two sparklines. The default tooltip formatter is kept on purpose (it escapes
// text), and nothing from the API except numbers reaches the chart.

export interface SparkSpec {
  name: string;
  points: [number, number][];
  color: string;
  /** Fixed y range (context fill is 0..1). */
  yMax?: number;
  /** Draw a dashed line at this y value (budget cap, compaction threshold). */
  guide?: number;
  unit: "pct" | "usd";
}

function fmt(v: number, unit: "pct" | "usd") {
  return unit === "pct" ? `${Math.round(v * 100)}%` : `$${v.toFixed(2)}`;
}

export function sparkOption(spec: SparkSpec, theme: ChartTheme) {
  const pts = spec.points.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1])).map(([t, v]) => [t / 60, v]);
  return {
    animation: false,
    color: [spec.color],
    grid: { left: 4, right: 4, top: 6, bottom: 4 },
    textStyle: { color: theme.muted },
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: theme.surface,
      borderColor: theme.border,
      textStyle: { color: theme.text, fontSize: 12 },
      valueFormatter: (v: unknown) => (typeof v === "number" ? fmt(v, spec.unit) : String(v)),
    },
    xAxis: { type: "value", show: false, min: "dataMin", max: "dataMax" },
    yAxis: { type: "value", show: false, min: 0, max: spec.yMax ?? "dataMax", scale: false },
    series: [
      {
        name: spec.name,
        type: "line",
        data: pts,
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 1.8 },
        areaStyle: { opacity: 0.12 },
        markLine:
          spec.guide != null
            ? { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: theme.muted, type: "dashed", width: 1 }, data: [{ yAxis: spec.guide }] }
            : undefined,
      },
    ],
  };
}
