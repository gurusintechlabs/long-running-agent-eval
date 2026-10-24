import { useEffect, useState, type ReactNode } from "react";
import { Badge, StateBadge } from "../../components";
import { formatDuration } from "../../lib/format";
import { Icon } from "./icons";
import type { LiveSnapshot } from "./types";

/** Wall-clock "now", re-rendered every second while `active`. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

export const STALL_AFTER_S = 120;

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="ss-item">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/**
 * The top strip: run state, elapsed, next-checkpoint ETA, scoring in flight, last-activity age. Numbers from
 * the last /live answer are advanced locally by the time since it arrived, so the clocks tick between polls.
 */
export function StatusStrip({ snap, fetchedAt, replay }: { snap: LiveSnapshot; fetchedAt: number; replay: boolean }) {
  const now = useNow(snap.live);
  const drift = snap.live ? Math.max(0, (now - fetchedAt) / 1000) : 0;
  const c = snap.clock;
  const elapsed = c.elapsed_s != null ? c.elapsed_s + drift : null;
  const next = snap.checkpoints.next;
  const due = next?.due_in_s != null ? next.due_in_s - drift : null;
  const sc = snap.checkpoints.scoring;
  const act = snap.activity;
  const idle = snap.live ? (act.idle_s != null ? act.idle_s + drift : act.last_event_age_s != null ? act.last_event_age_s + drift : null) : null;
  const stalled = snap.live && ((idle != null && idle >= STALL_AFTER_S) || snap.telemetry.stalled);
  const ended = snap.ended || !snap.live;

  return (
    <dl className="ss" aria-label="Run status">
      <Item label="State">
        <StateBadge state={snap.end?.state ?? snap.state} live={snap.live} />
        {replay && <span className="muted"> replay</span>}
      </Item>
      <Item label="Elapsed">
        <strong>{formatDuration(elapsed)}</strong>
        {c.duration_limit_s != null && <span className="muted"> of {formatDuration(c.duration_limit_s)}</span>}
      </Item>
      <Item label="Next checkpoint">
        {ended || !next ? (
          <span className="muted">{ended ? "none (run is over)" : "none planned"}</span>
        ) : due != null && due < 0 ? (
          <span>
            #{next.k} <strong className="ss-warn">overdue {formatDuration(-due)}</strong>
          </span>
        ) : (
          <span>
            #{next.k} in <strong>{formatDuration(due)}</strong>
          </span>
        )}
      </Item>
      <Item label="Scoring">
        {sc.in_flight.length > 0 ? (
          <Badge tone="info" live>checkpoint {sc.in_flight.join(", ")} in flight</Badge>
        ) : (
          <span className="muted">{sc.queued > 0 ? `${sc.finished} of ${sc.queued} scored` : "nothing queued"}</span>
        )}
      </Item>
      <Item label="Last activity">
        {!snap.live ? (
          <span className="muted">{ended ? "run is over" : "unknown"}</span>
        ) : idle == null ? (
          <span className="muted">none yet</span>
        ) : (
          <>
            <strong>{formatDuration(idle)}</strong> ago
            {stalled && (
              <span className="ss-stall" role="status" title="No agent activity for a while. The agent may be thinking or waiting on a tool, or it may be stalled. This is only a hint.">
                <Icon name="info" size={13} /> stalled?
              </span>
            )}
          </>
        )}
      </Item>
      <Item label="Tools">
        <span>{act.tool_calls}</span>
        <span className="muted"> calls</span>
        {act.tool_errors > 0 && <span className="muted"> {"·"} {act.tool_errors} errors</span>}
        {act.last_test_run && (
          <span className="muted"> {"·"} tests {act.last_test_run.passed}{"✓"}{act.last_test_run.failed + act.last_test_run.errors > 0 ? ` ${act.last_test_run.failed + act.last_test_run.errors}✗` : ""}</span>
        )}
      </Item>
      <Item label="Safety">
        <a href="#safety" className={`ss-safety ss-safety-${snap.safety.status}`}>
          {snap.safety.status}
          {snap.safety.status !== "clear" && (
            <span className="muted"> {"·"} {snap.safety.kills + snap.safety.violations + snap.safety.warnings}</span>
          )}
        </a>
      </Item>
    </dl>
  );
}
