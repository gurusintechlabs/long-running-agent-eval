import { Link } from "react-router-dom";
import type { RunSummary } from "../../api";
import { Badge, StateBadge, Table, type Column, type SortState } from "../../components";
import { EMPTY, formatDateTime, formatDuration, formatTokens, formatUsd } from "../../lib/format";
import { runDuration } from "./filter";

export const RUN_COLUMNS: Column<RunSummary>[] = [
  {
    key: "run",
    header: "Run",
    sortValue: (r) => r.run_id,
    render: (r) => (
      <Link to={`/runs/${encodeURIComponent(r.run_id)}`} className="mono run-link">
        {r.run_id}
      </Link>
    ),
  },
  {
    key: "state",
    header: "State",
    sortValue: (r) => (r.live ? "0 live" : `1 ${r.state ?? ""}`),
    render: (r) => (
      <span className="state-cell">
        <StateBadge state={r.state} live={r.live} />
        {r.live && <span className="visually-hidden"> (live)</span>}
        {r.resumed && <Badge tone="neutral" plain title="This run was resumed from a checkpoint">resumed</Badge>}
      </span>
    ),
  },
  { key: "experiment", header: "Experiment", sortValue: (r) => r.experiment_id, render: (r) => r.experiment_id ?? EMPTY },
  { key: "model", header: "Model", sortValue: (r) => r.model, render: (r) => <span className="mono">{r.model ?? EMPTY}</span> },
  { key: "started", header: "Started", sortValue: (r) => r.start_epoch, render: (r) => formatDateTime(r.start_epoch) },
  {
    key: "duration",
    header: "Duration",
    numeric: true,
    sortValue: (r) => runDuration(r),
    render: (r) => formatDuration(runDuration(r)),
  },
  {
    key: "cost",
    header: "Est. cost",
    headerLabel: "Est. cost (estimated, API-equivalent)",
    numeric: true,
    sortValue: (r) => r.cost_usd,
    render: (r) => formatUsd(r.cost_usd),
  },
  { key: "tokens", header: "Tokens", numeric: true, sortValue: (r) => r.tokens, render: (r) => formatTokens(r.tokens) },
  {
    key: "hazards",
    header: "Hazards",
    numeric: true,
    sortValue: (r) => r.hazard_count,
    render: (r) =>
      r.hazard_count == null ? (
        <span className="muted" title="Not ingested yet: hazards come from the metrics store">
          {EMPTY}
        </span>
      ) : r.hazard_count > 0 ? (
        <Badge tone="warn" plain>{r.hazard_count}</Badge>
      ) : (
        "0"
      ),
  },
  { key: "checkpoints", header: "Checkpoints", numeric: true, sortValue: (r) => r.checkpoints, render: (r) => String(r.checkpoints) },
  {
    key: "ingested",
    header: "Ingested",
    sortValue: (r) => (r.ingested ? 1 : 0),
    render: (r) => (r.ingested ? <Badge tone="ok" plain>yes</Badge> : <Badge tone="neutral" plain title="Not in metrics.sqlite yet">no</Badge>),
  },
];

export function RunsTable({
  runs,
  caption,
  sort,
  onSortChange,
}: {
  runs: RunSummary[];
  caption: string;
  sort: SortState | null;
  onSortChange: (s: SortState | null) => void;
}) {
  return <Table columns={RUN_COLUMNS} rows={runs} rowKey={(r) => r.run_id} caption={caption} sort={sort} onSortChange={onSortChange} />;
}
