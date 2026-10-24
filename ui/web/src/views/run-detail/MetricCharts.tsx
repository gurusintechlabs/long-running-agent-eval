import { useMemo, useState } from "react";
import type { CheckpointRow, Hazard } from "../../api";
import { Card, LazyChart, useChartTheme } from "../../components";
import type { ChartTheme } from "../../components/chart/theme";
import { CORE_METRICS, availableMetrics, metricLabel, seriesFor } from "../../lib/metrics";

export function buildOption(metric: string, cps: CheckpointRow[], hazards: Hazard[], theme: ChartTheme, color: string) {
  const data = seriesFor(cps, metric);
  const lines = hazards
    .filter((h) => h.t_attributed_s != null)
    .map((h) => ({ xAxis: (h.t_attributed_s as number) / 60, name: h.dimension }));
  return {
    animation: false,
    color: [color],
    grid: { left: 44, right: 14, top: 14, bottom: 28 },
    textStyle: { color: theme.muted },
    tooltip: {
      trigger: "axis",
      backgroundColor: theme.surface,
      borderColor: theme.border,
      textStyle: { color: theme.text },
      // Default formatter on purpose: it escapes names, so nothing from the data is interpreted as HTML (UI-5).
      valueFormatter: (v: unknown) => (typeof v === "number" ? String(Math.round(v * 1000) / 1000) : String(v)),
    },
    xAxis: {
      type: "value",
      name: "min",
      nameLocation: "end",
      nameTextStyle: { color: theme.muted },
      axisLabel: { color: theme.muted },
      axisLine: { lineStyle: { color: theme.grid } },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      scale: !["P", "R", "C", "X"].includes(metric),
      axisLabel: { color: theme.muted },
      splitLine: { lineStyle: { color: theme.grid } },
    },
    series: [
      {
        name: metric,
        type: "line",
        data,
        showSymbol: true,
        symbolSize: 7,
        lineStyle: { width: 2.2 },
        markLine: lines.length
          ? {
              silent: true,
              symbol: "none",
              lineStyle: { color: theme.muted, type: "dashed", width: 1 },
              label: { color: theme.muted, formatter: "{b}", fontSize: 10 },
              data: lines,
            }
          : undefined,
      },
    ],
  };
}

function MetricChart({ metric, cps, hazards, color }: { metric: string; cps: CheckpointRow[]; hazards: Hazard[]; color: string }) {
  const theme = useChartTheme();
  const option = useMemo(() => buildOption(metric, cps, hazards, theme, color), [metric, cps, hazards, theme, color]);
  return (
    <figure className="metric-fig">
      <figcaption>
        <strong className="mono">{metric}</strong> <span className="muted">{metricLabel(metric)}</span>
      </figcaption>
      <LazyChart option={option} height={170} label={`${metricLabel(metric)} (${metric}) per checkpoint`} />
    </figure>
  );
}

export function MetricCharts({ checkpoints, hazards }: { checkpoints: CheckpointRow[]; hazards: Hazard[] }) {
  const theme = useChartTheme();
  const metrics = useMemo(() => availableMetrics(checkpoints), [checkpoints]);
  const defaults = useMemo(() => metrics.filter((m) => (CORE_METRICS as readonly string[]).includes(m)), [metrics]);
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const selected = picked ?? new Set(defaults.length ? defaults : metrics.slice(0, 4));

  const toggle = (m: string) => {
    const next = new Set(selected);
    if (next.has(m)) next.delete(m);
    else next.add(m);
    setPicked(next);
  };

  return (
    <Card
      title="Metrics per checkpoint"
      actions={
        <div className="row">
          <button type="button" className="btn" onClick={() => setPicked(new Set(defaults))}>
            Core
          </button>
          <button type="button" className="btn" onClick={() => setPicked(new Set(metrics))}>
            All
          </button>
        </div>
      }
    >
      <div className="picker" role="group" aria-label="Choose metrics to chart">
        {metrics.map((m) => (
          <button
            key={m}
            type="button"
            className={`chip${selected.has(m) ? " chip-on" : ""}`}
            aria-pressed={selected.has(m)}
            title={metricLabel(m)}
            onClick={() => toggle(m)}
          >
            {m}
          </button>
        ))}
      </div>
      {selected.size === 0 ? (
        <p className="muted">Pick at least one metric above.</p>
      ) : (
        <div className="metric-grid">
          {metrics
            .filter((m) => selected.has(m))
            .map((m) => (
              <MetricChart key={m} metric={m} cps={checkpoints} hazards={hazards} color={theme.series[metrics.indexOf(m) % theme.series.length]} />
            ))}
        </div>
      )}
      <p className="muted chart-note">Dashed lines mark when a hazard was attributed. X axis is minutes since the run started.</p>
    </Card>
  );
}
