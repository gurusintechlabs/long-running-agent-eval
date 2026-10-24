import { useEffect } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, useAsync, type RunSummary } from "../../api";
import { Badge, Card, EmptyState, ErrorState, Spinner, StateBadge } from "../../components";
import { formatUsd } from "../../lib/format";

function RunLink({ r }: { r: RunSummary }) {
  return (
    <li>
      <Link className="rp-link" to={`/runs/${encodeURIComponent(r.run_id)}/live`}>
        <span className="rp-id mono">{r.run_id}</span>
        <span className="rp-meta">
          <StateBadge state={r.state} live={r.live} />
          <span className="muted">{r.model ?? "unknown model"}</span>
          <span className="muted">{r.checkpoints} checkpoints</span>
          <span className="muted">{formatUsd(r.cost_usd)}</span>
          <Badge tone={r.live ? "info" : "neutral"} plain>{r.live ? "watch live" : "replay"}</Badge>
        </span>
      </Link>
    </li>
  );
}

/** `/live` without a run id: go straight to the one active run, otherwise pick one. */
export function RunPicker() {
  const q = useAsync((s) => api.runs(s), [], (d) => (d && d.runs.some((r) => r.live) ? 4000 : null));
  useEffect(() => {
    document.title = "Live · LRAE";
  }, []);
  if (q.error && !q.data) return <ErrorState title="Could not load the runs" error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Spinner label="Loading runs" />;
  const runs = [...q.data.runs].sort((a, b) => (b.start_epoch ?? 0) - (a.start_epoch ?? 0));
  const live = runs.filter((r) => r.live);
  if (live.length === 1) return <Navigate to={`/runs/${encodeURIComponent(live[0].run_id)}/live`} replace />;
  const rest = runs.filter((r) => !r.live).slice(0, 15);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Live</h1>
          <div className="page-sub">{live.length ? `${live.length} runs are active` : "No run is active. Pick a finished run to replay its feed and safety record."}</div>
        </div>
      </div>
      {live.length > 0 && (
        <Card title="Running now" flush>
          <ul className="rp-list">{live.map((r) => <RunLink key={r.run_id} r={r} />)}</ul>
        </Card>
      )}
      <Card title="Replay a finished run" flush>
        {rest.length === 0 ? <EmptyState title="No runs yet">Launch one from the Launch page.</EmptyState> : <ul className="rp-list">{rest.map((r) => <RunLink key={r.run_id} r={r} />)}</ul>}
      </Card>
    </>
  );
}
