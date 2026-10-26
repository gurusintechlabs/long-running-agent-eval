import { useState } from "react";
import type { CompareResponse, CompareRun } from "../../api";
import { Badge, Card } from "../../components";
import { formatDuration, formatNumber, formatTokens, formatUsd } from "../../lib/format";
import { metricLabel } from "../../lib/metrics";

const SUMMARY_LABEL: Record<string, string> = {
  duration_s: "Duration",
  ttfh_s: "Time to first hazard",
  cost_usd: "Cost (estimated, API-equivalent)",
  tokens: "Tokens",
  hazard_count: "Hazards",
  checkpoints: "Checkpoints",
};

const SUMMARY_FMT: Record<string, (v: number | null) => string> = {
  duration_s: formatDuration,
  ttfh_s: formatDuration,
  cost_usd: formatUsd,
  tokens: formatTokens,
  hazard_count: (v) => formatNumber(v, 0),
  checkpoints: (v) => formatNumber(v, 0),
};

export function signed(d: number | null | undefined, fmt: (v: number) => string): string {
  if (d == null || !Number.isFinite(d)) return "";
  if (d === 0) return "±0";
  return `${d > 0 ? "+" : "−"}${fmt(Math.abs(d))}`;
}

function runTag(r: CompareRun): string {
  return `${r.summary.config ?? "?"} · r${r.summary.repeat ?? "?"}`;
}

export function DeltaTable({ data }: { data: CompareResponse }) {
  const runs = data.runs;
  const [all, setAll] = useState(false);
  const shown = all ? data.metric_deltas : data.metric_deltas.filter((m) => !/^(lrae|trace)\./.test(m.metric));
  const hiddenCount = data.metric_deltas.length - shown.length;
  const cell = (key: string, v: number | null | undefined, d: number | null | undefined, fmt: (v: number | null) => string, base: boolean) => (
    <td className="num" key={key}>
      <div>{fmt(v ?? null)}</div>
      {!base && d != null && <div className={`delta ${d > 0 ? "delta-up" : d < 0 ? "delta-down" : ""}`}>{signed(d, (x) => fmt(x))}</div>}
    </td>
  );
  return (
    <Card title="Deltas" flush>
      <div className="table-wrap">
        <table className="table delta-table">
          <caption className="visually-hidden">Final values and differences against the first selected run</caption>
          <thead>
            <tr>
              <th scope="col">Value</th>
              {runs.map((r) => (
                <th scope="col" key={r.run_id} className="num">
                  <div className="mono dt-id" title={r.run_id}>{r.run_id}</div>
                  <div className="muted dt-tag">
                    {runTag(r)} {r.run_id === data.base && <Badge tone="info" plain>base</Badge>}
                    {!r.ingested && <Badge tone="warn" plain>not ingested</Badge>}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.summary_deltas.map((s) => (
              <tr key={s.field}>
                <th scope="row">{SUMMARY_LABEL[s.field] ?? s.field}</th>
                {runs.map((r) => cell(r.run_id, s.values[r.run_id], s.delta_vs_base[r.run_id], SUMMARY_FMT[s.field] ?? ((v) => formatNumber(v)), r.run_id === data.base))}
              </tr>
            ))}
            <tr className="dt-sep">
              <th scope="row" colSpan={runs.length + 1}>
                Metrics, value at the last checkpoint
              </th>
            </tr>
            {shown.map((m) => (
              <tr key={m.metric}>
                <th scope="row" title={metricLabel(m.metric)}>
                  <span className="mono">{m.metric}</span> <span className="muted">{metricLabel(m.metric)}</span>
                </th>
                {runs.map((r) => cell(r.run_id, m.final[r.run_id], m.delta_vs_base[r.run_id], (v) => formatNumber(v, 3), r.run_id === data.base))}
              </tr>
            ))}
            {data.metric_deltas.length === 0 && (
              <tr>
                <td colSpan={runs.length + 1} className="muted">
                  No ingested metrics for the selected runs.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {(hiddenCount > 0 || all) && (
        <div className="dt-note">
          <button type="button" className="btn" onClick={() => setAll((a) => !a)}>
            {all ? "Hide detector metrics" : `Show ${hiddenCount} more behaviour-detector metrics`}
          </button>
        </div>
      )}
      <p className="muted chart-note dt-note">Differences are against the first selected run (the base). {data.cost_note}.</p>
    </Card>
  );
}

export function HazardTable({ data }: { data: CompareResponse }) {
  const rows = data.runs.flatMap((r) => r.hazards.map((h) => ({ run: r.run_id, ...h })));
  return (
    <Card title={`Hazards (${rows.length})`} flush>
      {rows.length === 0 ? (
        <p className="muted card-pad">No hazards recorded for the selected runs (or none of them is ingested).</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <caption className="visually-hidden">Hazards of the selected runs</caption>
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Dimension</th>
                <th scope="col">Rule</th>
                <th scope="col" className="num">Time</th>
                <th scope="col" className="num">k</th>
                <th scope="col">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => (
                <tr key={`${h.run}:${h.dimension}`}>
                  <td className="mono dt-id" title={h.run}>{h.run}</td>
                  <td>{h.dimension}</td>
                  <td className="mono">{h.rule}</td>
                  <td className="num">{formatDuration(h.t_attributed_s)}</td>
                  <td className="num">{h.k ?? "–"}</td>
                  <td className="dt-evidence">{h.evidence ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
