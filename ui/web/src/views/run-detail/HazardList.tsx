import type { Hazard } from "../../api";
import { Badge, Card, EmptyState } from "../../components";
import { EMPTY, formatDuration } from "../../lib/format";

const DIMENSION_TONE: Record<string, "bad" | "warn" | "info"> = { safety: "bad", context: "warn", cost: "warn" };

/** Evidence strings come from the harness (and ultimately from agent output): always rendered as text. */
export function HazardList({ hazards, ingested }: { hazards: Hazard[]; ingested: boolean }) {
  return (
    <Card title={`Hazards${ingested ? ` (${hazards.length})` : ""}`}>
      {!ingested ? (
        <EmptyState title="Hazards need ingest">Hazards are computed when the run is ingested into the metrics store.</EmptyState>
      ) : hazards.length === 0 ? (
        <EmptyState title="No hazards recorded">The run stayed inside every threshold.</EmptyState>
      ) : (
        <ol className="hazards">
          {hazards.map((h, i) => (
            <li key={`${h.dimension}-${h.rule}-${h.t_attributed_s}-${i}`} className="hazard">
              <div className="row hz-head">
                <Badge tone={DIMENSION_TONE[h.dimension] ?? "info"}>{h.dimension}</Badge>
                <span className="mono hz-rule">{h.rule}</span>
                {h.k != null && <span className="muted">at checkpoint t{h.k}</span>}
              </div>
              <div className="muted hz-times">
                attributed at {formatDuration(h.t_attributed_s)}
                {h.t_detected_s != null && h.t_detected_s !== h.t_attributed_s && <>, detected at {formatDuration(h.t_detected_s)}</>}
              </div>
              <pre className="hz-evidence">{h.evidence || EMPTY}</pre>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
