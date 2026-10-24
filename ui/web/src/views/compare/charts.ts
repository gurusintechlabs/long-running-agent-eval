// Pure ECharts option builders for the Compare view (kept apart from React so they are unit-testable).
// Names that come from data (run ids, configs, hazard dimensions) only ever reach ECharts as plain strings
// and the default tooltip formatter, which escapes them (UI-5). No custom HTML formatters here.
import type { CompareRun, SeriesPoints, SurvivalGroup } from "../../api";
import type { ChartTheme } from "../../components/chart/theme";

export type XAxis = "k" | "t";

export interface OverlayLine {
  name: string;
  color: string;
  points: [number, number][];
  /** Vertical dashed markers (hazards). */
  marks: { x: number; label: string }[];
}

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** [x, y] pairs for one series on the chosen axis: x is the checkpoint k or the run time in minutes. */
export function pointsOf(s: SeriesPoints | undefined, axis: XAxis): [number, number][] {
  if (!s) return [];
  const out: [number, number][] = [];
  s.k.forEach((k, i) => {
    const y = s.value[i];
    const x = axis === "k" ? k : s.t_s[i] == null ? null : (s.t_s[i] as number) / 60;
    if (finite(x) && finite(y)) out.push([x, y]);
  });
  return out;
}

export function hazardMarks(run: CompareRun, axis: XAxis): { x: number; label: string }[] {
  const out: { x: number; label: string }[] = [];
  for (const h of run.hazards) {
    const x = axis === "k" ? h.k : h.t_attributed_s == null ? null : h.t_attributed_s / 60;
    if (finite(x)) out.push({ x, label: h.dimension });
  }
  return out;
}

export function overlayLines(runs: CompareRun[], pick: (r: CompareRun) => SeriesPoints | undefined, axis: XAxis, colors: string[], withMarks: boolean): OverlayLine[] {
  return runs.map((r, i) => ({
    name: r.run_id,
    color: colors[i % colors.length],
    points: pointsOf(pick(r), axis),
    marks: withMarks ? hazardMarks(r, axis) : [],
  }));
}

function baseAxes(theme: ChartTheme, xName: string, yName: string, zeroBased: boolean) {
  return {
    animation: false,
    textStyle: { color: theme.muted },
    grid: { left: 52, right: 18, top: 36, bottom: 62 },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.surface,
      borderColor: theme.border,
      textStyle: { color: theme.text },
      // Default formatter on purpose: it escapes names (UI-5).
      valueFormatter: (v: unknown) => (typeof v === "number" ? String(Math.round(v * 1000) / 1000) : String(v)),
    },
    legend: { type: "scroll", bottom: 0, textStyle: { color: theme.muted }, pageTextStyle: { color: theme.muted } },
    xAxis: {
      type: "value",
      name: xName,
      nameLocation: "middle",
      nameGap: 26,
      nameTextStyle: { color: theme.muted },
      min: 0,
      axisLabel: { color: theme.muted },
      axisLine: { lineStyle: { color: theme.grid } },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      name: yName,
      nameTextStyle: { color: theme.muted, align: "left" },
      scale: !zeroBased,
      axisLabel: { color: theme.muted },
      splitLine: { lineStyle: { color: theme.grid } },
    },
  };
}

export function buildOverlayOption(lines: OverlayLine[], theme: ChartTheme, opts: { xName: string; yName: string; zeroBased?: boolean; step?: boolean }) {
  return {
    ...baseAxes(theme, opts.xName, opts.yName, opts.zeroBased ?? false),
    color: lines.map((l) => l.color),
    series: lines.map((l) => ({
      name: l.name,
      type: "line",
      data: l.points,
      step: opts.step ? "end" : undefined,
      showSymbol: l.points.length < 60,
      symbolSize: 6,
      lineStyle: { width: 2.2, color: l.color },
      itemStyle: { color: l.color },
      markLine: l.marks.length
        ? {
            silent: true,
            symbol: "none",
            lineStyle: { color: l.color, type: "dashed", width: 1.2, opacity: 0.85 },
            label: { color: theme.muted, formatter: "{b}", fontSize: 10, position: "insideEndTop" },
            data: l.marks.map((m) => ({ xAxis: m.x, name: m.label })),
          }
        : undefined,
    })),
  };
}

// ---------------------------------------------------------------- survival

export interface SurvivalSeriesData {
  label: string;
  /** Step points including the origin (0, 1). */
  step: [number, number][];
  lower: [number, number][];
  /** upper - lower, drawn stacked on `lower` to make a band. */
  band: [number, number][];
  censors: [number, number][];
  headlineMin: number | null;
  medianMin: number | null;
}

const min = (s: number) => s / 60;

export function survivalData(g: SurvivalGroup): SurvivalSeriesData | null {
  const km = g.km;
  if (!g.available || !km || km.times.length === 0) return null;
  const t = [0, ...km.times.map(min)];
  const s = [1, ...km.surv];
  const lo = [1, ...km.lower.map((v) => v ?? 0)];
  const hi = [1, ...km.upper.map((v) => v ?? 1)];
  const zip = (ys: number[]): [number, number][] => t.map((x, i) => [x, ys[i]]);
  return {
    label: g.label,
    step: zip(s),
    lower: zip(lo),
    band: zip(hi.map((h, i) => Math.max(0, h - lo[i]))),
    censors: km.censor_times.map((c, i) => [min(c), km.censor_surv[i]] as [number, number]),
    headlineMin: g.headline_available && finite(g.headline_s) ? min(g.headline_s) : null,
    medianMin: finite(g.median_s) ? min(g.median_s as number) : null,
  };
}

const TICK = "path://M0,-7 L0,7";

export function buildSurvivalOption(groups: SurvivalGroup[], theme: ChartTheme) {
  const data = groups.map(survivalData);
  const series: object[] = [];
  const colors: string[] = [];
  data.forEach((d, i) => {
    if (!d) return;
    const c = theme.series[i % theme.series.length];
    colors.push(c);
    series.push(
      {
        name: `${d.label} lower`,
        type: "line",
        data: d.lower,
        step: "end",
        stack: `ci${i}`,
        symbol: "none",
        silent: true,
        lineStyle: { opacity: 0 },
        tooltip: { show: false },
      },
      {
        name: `${d.label} band`,
        type: "line",
        data: d.band,
        step: "end",
        stack: `ci${i}`,
        symbol: "none",
        silent: true,
        lineStyle: { opacity: 0 },
        areaStyle: { color: c, opacity: 0.16 },
        tooltip: { show: false },
      },
      {
        name: d.label,
        type: "line",
        data: d.step,
        step: "end",
        symbol: "none",
        lineStyle: { width: 2.4, color: c },
        itemStyle: { color: c },
        markLine: d.headlineMin != null ? {
          silent: true,
          symbol: "none",
          lineStyle: { color: c, type: "dotted", width: 1.5 },
          label: { color: theme.muted, formatter: "limit", fontSize: 10, position: "insideEndTop" },
          data: [{ xAxis: d.headlineMin }],
        } : undefined,
      },
      {
        name: `${d.label} censored`,
        type: "line",
        data: d.censors,
        symbol: TICK,
        symbolSize: 12,
        lineStyle: { opacity: 0 },
        itemStyle: { color: c, borderWidth: 2 },
        z: 5,
      },
    );
  });
  const names = data.filter((d): d is SurvivalSeriesData => !!d).map((d) => d.label);
  return {
    animation: false,
    textStyle: { color: theme.muted },
    grid: { left: 52, right: 18, top: 34, bottom: 62 },
    tooltip: {
      trigger: "item",
      backgroundColor: theme.surface,
      borderColor: theme.border,
      textStyle: { color: theme.text },
      valueFormatter: (v: unknown) => (typeof v === "number" ? String(Math.round(v * 1000) / 1000) : String(v)),
    },
    legend: { type: "scroll", bottom: 0, data: names, textStyle: { color: theme.muted }, pageTextStyle: { color: theme.muted } },
    xAxis: {
      type: "value",
      name: "minutes of agent time",
      nameLocation: "middle",
      nameGap: 26,
      nameTextStyle: { color: theme.muted },
      min: 0,
      axisLabel: { color: theme.muted },
      axisLine: { lineStyle: { color: theme.grid } },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      name: "S(t): runs without a hazard",
      nameTextStyle: { color: theme.muted, align: "left" },
      min: 0,
      max: 1,
      axisLabel: { color: theme.muted },
      splitLine: { lineStyle: { color: theme.grid } },
    },
    color: colors,
    series,
  };
}
