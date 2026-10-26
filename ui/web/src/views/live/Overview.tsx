import { useMemo } from "react";
import { Card, LazyChart, useChartTheme } from "../../components";
import { formatUsd } from "../../lib/format";
import { BudgetMeter } from "./BudgetMeter";
import { sparkOption } from "./liveCharts";
import type { LiveSnapshot } from "./types";

function Spark({ title, value, note, spec }: { title: string; value: string; note?: string; spec: Parameters<typeof sparkOption>[0] }) {
  const theme = useChartTheme();
  const option = useMemo(() => sparkOption(spec, theme), [spec, theme]);
  const has = spec.points.length > 1;
  return (
    <div className="sk">
      <div className="sk-head">
        <span className="sk-title">{title}</span>
        <span className="sk-value">{value}</span>
      </div>
      <div className="sk-chart">
        {has ? <LazyChart option={option} height={56} label={`${title} over the run`} /> : <div className="sk-empty muted">No data yet</div>}
      </div>
      {note && <div className="sk-note muted">{note}</div>}
    </div>
  );
}

export function CheckpointProgress({ snap }: { snap: LiveSnapshot }) {
  const cp = snap.checkpoints;
  const planned = Math.max(cp.planned ?? 0, cp.taken);
  const inFlight = new Set(cp.scoring.in_flight);
  const next = cp.next?.k;
  const cells = Array.from({ length: Math.min(planned, 60) }, (_, i) => i + 1);
  return (
    <div className="cpp">
      <div className="cpp-head">
        <span className="sk-title">Checkpoints</span>
        <span className="sk-value">
          {cp.taken}
          {cp.planned != null ? ` of ${cp.planned}` : ""}
        </span>
      </div>
      <ol className="cpp-cells" aria-label="Checkpoint progress">
        {cells.map((k) => {
          const taken = k <= cp.taken;
          const state = inFlight.has(k) ? "scoring" : taken ? "taken" : k === next ? "next" : "todo";
          const label = state === "scoring" ? "taken, being scored" : state === "taken" ? "taken" : state === "next" ? "next" : "planned";
          return (
            <li key={k} className={`cpp-cell cpp-${state}`} title={`Checkpoint ${k}: ${label}`}>
              <span className="visually-hidden">{`Checkpoint ${k}: ${label}`}</span>
            </li>
          );
        })}
      </ol>
      <div className="sk-note muted">
        {cp.scoring.finished} scored{cp.scoring.in_flight.length ? `, ${cp.scoring.in_flight.length} in flight` : ""}
        {cp.last?.cumulative_cost_usd != null ? ` · last cp cost ${formatUsd(cp.last.cumulative_cost_usd)}` : ""}
      </div>
    </div>
  );
}

export function Overview({ snap }: { snap: LiveSnapshot }) {
  const theme = useChartTheme();
  const ctxSpec = useMemo(
    () => ({ name: "Context fill", points: snap.series?.context_fill ?? [], color: theme.series[3], yMax: 1, guide: 0.9, unit: "pct" as const }),
    [snap.series?.context_fill, theme.series],
  );
  const costSpec = useMemo(
    () => ({ name: "Cost", points: snap.series?.cost_usd ?? [], color: theme.series[0], guide: snap.budget.per_run_usd ?? undefined, unit: "usd" as const }),
    [snap.series?.cost_usd, snap.budget.per_run_usd, theme.series],
  );
  const ctx = snap.context;
  return (
    <Card className="ov" title="Budget and progress">
      <div className="ov-grid">
        <BudgetMeter meter={snap.budget} costUsd={snap.cost.usd} tokens={snap.cost.tokens.total} elapsedS={snap.clock.elapsed_s} />
        <div className="ov-charts">
          <Spark
            title="Context fill"
            value={ctx.fill != null ? `${Math.round(ctx.fill * 100)}%` : "–"}
            note={ctx.max_fill != null ? `peak ${Math.round(ctx.max_fill * 100)}%${ctx.compactions ? ` · ${ctx.compactions} compaction${ctx.compactions === 1 ? "" : "s"}` : ""}` : undefined}
            spec={ctxSpec}
          />
          <Spark
            title="Cost"
            value={snap.cost.usd != null ? `$${snap.cost.usd.toFixed(2)}` : "–"}
            note={snap.budget.burn_usd_per_min != null ? `avg $${snap.budget.burn_usd_per_min.toFixed(2)}/min · estimated, API-equivalent` : "estimated, API-equivalent"}
            spec={costSpec}
          />
        </div>
        <CheckpointProgress snap={snap} />
      </div>
    </Card>
  );
}
