import { useMemo } from "react";
import { Link } from "react-router-dom";
import { JUDGE_METRICS, type CheckpointRow } from "../../api";
import { Badge, Card, EmptyState, Table, type Column } from "../../components";
import { EMPTY, formatDuration, formatNumber, shortSha } from "../../lib/format";
import { CORE_METRICS, metricLabel } from "../../lib/metrics";
import "./judges/judges.css";

/** The judges' verdicts at checkpoint ``c`` in a few badges, from the metric values (details are on the Judges tab). */
function JudgeSummary({ c }: { c: CheckpointRow }) {
  const m = c.metrics;
  const n = (name: string) => (typeof m[name] === "number" ? (m[name] as number) : null);
  const x = n(JUDGE_METRICS.x);
  const fid = n(JUDGE_METRICS.fidelity);
  const drift = n(JUDGE_METRICS.drift) ?? 0;
  const mis = n(JUDGE_METRICS.misstatements) ?? 0;
  const tac = n(JUDGE_METRICS.tactics) ?? 0;
  if (x == null && fid == null) return <>{EMPTY}</>;
  return (
    <span className="jd-row-chips">
      {x != null && <Badge tone={x > 0 ? "warn" : "ok"} plain title="Quality judge: contradictions (X)">X {formatNumber(x, 1)}</Badge>}
      {fid != null && <Badge tone="info" plain title="Goal observer: fidelity">fid {formatNumber(fid, 2)}</Badge>}
      {drift > 0 && <Badge tone="warn" plain title="Goal observer: drift items">{drift} drift</Badge>}
      {mis > 0 && <Badge tone="bad" plain title="Prose-claims audit: misstatements">{mis} misstated</Badge>}
      {tac > 0 && <Badge tone="bad" plain title="Manipulation check: tactics">{tac} tactic{tac === 1 ? "" : "s"}</Badge>}
    </span>
  );
}

export function CheckpointsTable({
  checkpoints,
  ingested,
  onOpen,
  judgesHref,
}: {
  checkpoints: CheckpointRow[];
  ingested: boolean;
  onOpen?: (k: number) => void;
  /** Link to this checkpoint on the Judges tab; adds the judge summary column. */
  judgesHref?: (k: number) => string;
}) {
  const columns = useMemo(() => {
    const cols: Column<CheckpointRow>[] = [
      { key: "k", header: "k", numeric: true, sortValue: (c) => c.k, render: (c) => `t${c.k}` },
      { key: "t", header: "Time", numeric: true, sortValue: (c) => c.t_s, render: (c) => formatDuration(c.t_s) },
      { key: "sha", header: "Head", render: (c) => <span className="mono" title={c.head_sha ?? undefined}>{shortSha(c.head_sha)}</span> },
      {
        key: "dirty",
        header: "Tree",
        render: (c) => (c.dirty == null ? EMPTY : c.dirty ? <Badge tone="warn" plain>uncommitted</Badge> : <Badge tone="ok" plain>clean</Badge>),
      },
      { key: "pause", header: "Pause", numeric: true, sortValue: (c) => c.pause_ms, render: (c) => (c.pause_ms == null ? EMPTY : `${Math.round(c.pause_ms)} ms`) },
    ];
    if (ingested) {
      const present = new Set<string>();
      for (const c of checkpoints) for (const m of Object.keys(c.metrics)) present.add(m);
      for (const m of CORE_METRICS) {
        if (!present.has(m)) continue;
        cols.push({
          key: `m-${m}`,
          header: m,
          headerLabel: metricLabel(m),
          numeric: true,
          sortValue: (c) => c.metrics[m],
          render: (c) => formatNumber(c.metrics[m], 3),
        });
      }
    }
    if (ingested && judgesHref && checkpoints.some((c) => JUDGE_METRICS.x in c.metrics || JUDGE_METRICS.fidelity in c.metrics)) {
      cols.push({
        key: "judges",
        header: "Judges",
        headerLabel: "What the LLM judges found",
        render: (c) => (
          <span className="jd-row-chips">
            <JudgeSummary c={c} />
            <Link to={judgesHref(c.k)} aria-label={`Judgements at checkpoint t${c.k}`}>details</Link>
          </span>
        ),
      });
    }
    if (onOpen) {
      cols.push({
        key: "open",
        header: "",
        headerLabel: "Details",
        render: (c) => (
          <button type="button" className="btn btn-small" onClick={() => onOpen(c.k)} aria-label={`Details for checkpoint t${c.k}`}>
            Diff and log
          </button>
        ),
      });
    }
    return cols;
  }, [checkpoints, ingested, onOpen, judgesHref]);

  return (
    <Card title={`Checkpoints (${checkpoints.length})`} flush>
      {checkpoints.length === 0 ? (
        <EmptyState title="No checkpoints yet">The first one is taken at the configured interval.</EmptyState>
      ) : (
        <Table columns={columns} rows={checkpoints} rowKey={(c) => String(c.k)} caption="Checkpoints" defaultSort={{ key: "k", dir: "asc" }} />
      )}
    </Card>
  );
}
