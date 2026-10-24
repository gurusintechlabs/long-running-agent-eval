import { useMemo } from "react";
import type { CheckpointRow } from "../../api";
import { Badge, Card, EmptyState, Table, type Column } from "../../components";
import { EMPTY, formatDuration, formatNumber, shortSha } from "../../lib/format";
import { CORE_METRICS, metricLabel } from "../../lib/metrics";

export function CheckpointsTable({ checkpoints, ingested }: { checkpoints: CheckpointRow[]; ingested: boolean }) {
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
    return cols;
  }, [checkpoints, ingested]);

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
