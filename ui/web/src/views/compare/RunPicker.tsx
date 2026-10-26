import { useMemo, useState } from "react";
import type { RunSummary } from "../../api";
import { Badge, Card, StateBadge } from "../../components";
import { formatDateTime } from "../../lib/format";

export const MAX_COMPARE = 8;

export function RunPicker({
  runs,
  selected,
  onChange,
}: {
  runs: RunSummary[];
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [q, setQ] = useState("");
  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return needle ? runs.filter((r) => `${r.run_id} ${r.experiment_id ?? ""} ${r.config ?? ""}`.toLowerCase().includes(needle)) : runs;
  }, [runs, q]);
  const full = selected.length >= MAX_COMPARE;

  const toggle = (id: string) => {
    if (selected.includes(id)) onChange(selected.filter((s) => s !== id));
    else if (!full) onChange([...selected, id]);
  };

  return (
    <Card
      title={`Runs to compare (${selected.length}/${MAX_COMPARE})`}
      actions={
        <button type="button" className="btn" disabled={selected.length === 0} onClick={() => onChange([])}>
          Clear
        </button>
      }
    >
      <label className="tb-field">
        <span className="visually-hidden">Filter runs</span>
        <input className="field" type="search" placeholder="Filter runs by id, experiment or config" value={q} onChange={(e) => setQ(e.target.value)} />
      </label>
      {runs.length === 0 ? (
        <p className="muted">There are no runs yet.</p>
      ) : (
        <ul className="picker-list" aria-label="Runs">
          {visible.map((r) => {
            const on = selected.includes(r.run_id);
            return (
              <li key={r.run_id} className={on ? "picker-row picker-on" : "picker-row"}>
                <label>
                  <input type="checkbox" checked={on} disabled={!on && full} onChange={() => toggle(r.run_id)} />
                  <span className="mono picker-id">{r.run_id}</span>
                </label>
                <span className="picker-meta">
                  <StateBadge state={r.state} live={r.live} />
                  {!r.ingested && (
                    <Badge tone="warn" title="Not in the metrics store: ingest to see metrics, hazards and cost series">
                      not ingested
                    </Badge>
                  )}
                  <span className="muted">{formatDateTime(r.start_epoch)}</span>
                </span>
              </li>
            );
          })}
          {visible.length === 0 && <li className="muted picker-row">No run matches the filter.</li>}
        </ul>
      )}
      {full && <p className="muted chart-note">At most {MAX_COMPARE} runs can be compared at once.</p>}
    </Card>
  );
}
