import { useEffect, useMemo, useState } from "react";
import { api, useAsync, type ExperimentGroup, type RunSummary } from "../../api";
import { Badge, Card, EmptyState, ErrorState, Spinner, StateBadge, type SortState } from "../../components";
import { formatUsd } from "../../lib/format";
import { filterRuns, groupByExperiment, NO_FILTERS, type RunFilters } from "./filter";
import { RunsTable } from "./RunsTable";
import "./runs.css";

const REFRESH_MS = 4000;
const DEFAULT_SORT: SortState = { key: "started", dir: "desc" };

export function RunsView() {
  const runsQ = useAsync((s) => api.runs(s), [], (d) => (d?.runs.some((r) => r.live) ? REFRESH_MS : null));
  const expQ = useAsync((s) => api.experiments(s), [], (d) => (d?.experiments.some((e) => e.live) ? REFRESH_MS : null));

  const [filters, setFilters] = useState<RunFilters>(NO_FILTERS);
  const [grouped, setGrouped] = useState(false);
  const [sort, setSort] = useState<SortState | null>(DEFAULT_SORT);

  const runs = useMemo(() => runsQ.data?.runs ?? [], [runsQ.data]);
  const visible = useMemo(() => filterRuns(runs, filters), [runs, filters]);
  const states = useMemo(() => [...new Set(runs.map((r) => r.state).filter((s): s is string => !!s))].sort(), [runs]);
  const anyLive = runs.some((r) => r.live);

  useEffect(() => {
    document.title = "Runs · LRAE";
  }, []);

  const groups = useMemo(
    () => groupByExperiment(visible, expQ.data?.experiments.map((e) => e.experiment_id) ?? []),
    [visible, expQ.data],
  );
  const expById = useMemo(() => new Map<string, ExperimentGroup>((expQ.data?.experiments ?? []).map((e) => [e.experiment_id, e])), [expQ.data]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Runs</h1>
          <div className="page-sub">
            {runsQ.data ? `${visible.length} of ${runs.length} runs` : "Loading runs"}
            {anyLive && " · refreshing every few seconds while a run is live"}
          </div>
        </div>
      </div>

      <Card flush>
        <form className="toolbar" role="search" aria-label="Filter runs" onSubmit={(e) => e.preventDefault()}>
          <label className="tb-field tb-grow">
            <span className="visually-hidden">Search runs</span>
            <input
              className="field"
              type="search"
              placeholder="Search run, experiment, model..."
              value={filters.search}
              onChange={(e) => setFilters({ ...filters, search: e.target.value })}
            />
          </label>
          <label className="tb-field">
            <span className="tb-label">State</span>
            <select className="field" value={filters.state} onChange={(e) => setFilters({ ...filters, state: e.target.value })}>
              <option value="">Any</option>
              {states.map((s) => (
                <option key={s} value={s}>
                  {s.toLowerCase().replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="tb-field">
            <span className="tb-label">Ingested</span>
            <select
              className="field"
              value={filters.ingested}
              onChange={(e) => setFilters({ ...filters, ingested: e.target.value as RunFilters["ingested"] })}
            >
              <option value="">Any</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>
          <label className="tb-check">
            <input type="checkbox" checked={filters.liveOnly} onChange={(e) => setFilters({ ...filters, liveOnly: e.target.checked })} />
            Live only
          </label>
          <label className="tb-check">
            <input type="checkbox" checked={grouped} onChange={(e) => setGrouped(e.target.checked)} />
            Group by experiment
          </label>
          {JSON.stringify(filters) !== JSON.stringify(NO_FILTERS) && (
            <button type="button" className="btn" onClick={() => setFilters(NO_FILTERS)}>
              Clear filters
            </button>
          )}
        </form>
      </Card>

      {runsQ.loading && <Spinner label="Loading runs" />}
      {runsQ.error && !runsQ.data && <ErrorState title="Could not load runs" error={runsQ.error} onRetry={runsQ.reload} />}

      {runsQ.data && runs.length === 0 && (
        <Card>
          <EmptyState title="No runs yet">
            Nothing with a <code>manifest.json</code> was found in the runs directory. Runs appear here as soon as they start.
          </EmptyState>
        </Card>
      )}

      {runsQ.data && runs.length > 0 && visible.length === 0 && (
        <Card>
          <EmptyState
            title="No runs match"
            action={
              <button type="button" className="btn" onClick={() => setFilters(NO_FILTERS)}>
                Clear filters
              </button>
            }
          >
            Try a different search or filter.
          </EmptyState>
        </Card>
      )}

      {visible.length > 0 && !grouped && (
        <Card flush>
          <RunsTable runs={visible} caption="Runs" sort={sort} onSortChange={setSort} />
        </Card>
      )}

      {visible.length > 0 &&
        grouped &&
        groups.map((g) => (
          <ExperimentCard key={g.id} id={g.id} runs={g.runs} summary={expById.get(g.id)} sort={sort} onSortChange={setSort} />
        ))}

      {visible.length > 0 && (
        <p className="footnote muted">
          Cost is <strong>estimated (API-equivalent)</strong> from Claude Code telemetry, not a bill. Hazards and duration need the run to be ingested.
        </p>
      )}
    </>
  );
}

function ExperimentCard({
  id,
  runs,
  summary,
  sort,
  onSortChange,
}: {
  id: string;
  runs: RunSummary[];
  summary?: ExperimentGroup;
  sort: SortState | null;
  onSortChange: (s: SortState | null) => void;
}) {
  const cost = runs.reduce((a, r) => a + (r.cost_usd ?? 0), 0);
  return (
    <Card
      flush
      title={<span className="mono">{id}</span>}
      actions={
        <span className="row">
          {summary?.live && <Badge tone="info" live>live</Badge>}
          {Object.entries(summary?.states ?? {}).map(([s, n]) => (
            <span key={s} className="row" style={{ gap: 4 }}>
              <StateBadge state={s} />
              <span className="muted">{n}</span>
            </span>
          ))}
          <span className="muted" title="Estimated (API-equivalent)">
            {runs.length} run{runs.length === 1 ? "" : "s"}
            {" · "}
            {formatUsd(cost)} est.
          </span>
        </span>
      }
    >
      <RunsTable runs={runs} caption={`Runs of ${id}`} sort={sort} onSortChange={onSortChange} />
    </Card>
  );
}
