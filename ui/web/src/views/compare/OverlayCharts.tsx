import { useMemo, useState, type ReactNode } from "react";
import type { CompareResponse } from "../../api";
import { Card, LazyChart, useChartTheme } from "../../components";
import { metricLabel } from "../../lib/metrics";
import { buildOverlayOption, overlayLines, type XAxis } from "./charts";

function Fig({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <figure className="metric-fig">
      <figcaption>
        <strong>{title}</strong> {note && <span className="muted">{note}</span>}
      </figcaption>
      {children}
    </figure>
  );
}

export function OverlayCharts({ data }: { data: CompareResponse }) {
  const theme = useChartTheme();
  const withData = data.runs.filter((r) => r.ingested);
  const [metricPick, setMetric] = useState<string | null>(null);
  const [axis, setAxis] = useState<XAxis>("t");
  const [marks, setMarks] = useState(true);
  const metric = metricPick && data.metrics.includes(metricPick) ? metricPick : data.metrics.includes("P") ? "P" : (data.metrics[0] ?? "");
  const xName = axis === "k" ? "checkpoint k" : "minutes of agent time";

  const metricOpt = useMemo(
    () =>
      buildOverlayOption(
        overlayLines(data.runs, (r) => r.series[metric], axis, theme.series, marks),
        theme,
        { xName, yName: metric, zeroBased: ["P", "R", "C", "X"].includes(metric) },
      ),
    [data, metric, axis, marks, theme, xName],
  );
  const costOpt = useMemo(
    () => buildOverlayOption(overlayLines(data.runs, (r) => r.counters.cum_cost_usd, axis, theme.series, marks), theme, { xName, yName: "USD, estimated", zeroBased: true }),
    [data, axis, marks, theme, xName],
  );
  const fillOpt = useMemo(
    () => buildOverlayOption(overlayLines(data.runs, (r) => r.counters.context_fill_max, axis, theme.series, marks), theme, { xName, yName: "context fill (max)", zeroBased: true }),
    [data, axis, marks, theme, xName],
  );
  const hasCost = withData.some((r) => r.counters.cum_cost_usd?.k.length);
  const hasFill = withData.some((r) => r.counters.context_fill_max?.k.length);

  if (withData.length === 0) {
    return (
      <Card title="Overlay">
        <p className="muted">None of the selected runs is in the metrics store yet, so there are no series to draw. Re-ingest from the banner above and they will appear.</p>
      </Card>
    );
  }

  return (
    <Card title="Overlay">
      <div className="ov-controls">
        <label className="tb-field">
          <span className="tb-label">Metric</span>
          <select className="field" value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Metric">
            {data.metrics.map((m) => (
              <option key={m} value={m}>
                {m} · {metricLabel(m)}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="seg" aria-label="X axis">
          <legend className="tb-label">X axis</legend>
          <label>
            <input type="radio" name="xaxis" checked={axis === "t"} onChange={() => setAxis("t")} /> run time
          </label>
          <label>
            <input type="radio" name="xaxis" checked={axis === "k"} onChange={() => setAxis("k")} /> checkpoint
          </label>
        </fieldset>
        <label className="tb-check">
          <input type="checkbox" checked={marks} onChange={(e) => setMarks(e.target.checked)} /> Hazard markers
        </label>
      </div>
      <div className="ov-grid">
        <Fig title={`${metric}`} note={metricLabel(metric)}>
          <LazyChart option={metricOpt} height={280} label={`${metricLabel(metric)} (${metric}) for the selected runs`} />
        </Fig>
        <Fig title="Cumulative cost" note="estimated (API-equivalent), not a bill">
          {hasCost ? <LazyChart option={costOpt} height={280} label="Cumulative estimated cost for the selected runs" /> : <p className="muted">No cost counters in the store for these runs.</p>}
        </Fig>
        <Fig title="Context fill" note="share of the context window, peak per checkpoint">
          {hasFill ? <LazyChart option={fillOpt} height={280} label="Context fill for the selected runs" /> : <p className="muted">No context-fill counters in the store for these runs.</p>}
        </Fig>
      </div>
      <p className="muted chart-note">
        Dashed vertical lines are hazards, in the run&apos;s colour, labelled with their dimension. {data.cost_note}.
      </p>
    </Card>
  );
}
