import { useState } from "react";
import { Link } from "react-router-dom";
import { controlApi, useAsync, type ControlState } from "../api";
import "../views/launch/launch.css";

export const CONTROL_POLL_ACTIVE_MS = 3000;
export const CONTROL_POLL_IDLE_MS = 8000;

/** Poll GET /api/control/state (faster while a run is active). */
export function useControlState() {
  return useAsync<ControlState>((s) => controlApi.state(s), [], (d) => (d?.active ? CONTROL_POLL_ACTIVE_MS : CONTROL_POLL_IDLE_MS));
}

/**
 * Always-visible strip in the shell: which run (if any) is active, a link to its page, the launch-log
 * tail on demand, and why launching is not allowed while a run is active (one run at a time).
 */
export function ControlBar() {
  const q = useControlState();
  const [open, setOpen] = useState(false);
  const st = q.data;

  if (!st) {
    // Unknown (loading or the control API is unavailable): stay quiet, do not alarm.
    return q.error ? (
      <div className="control-bar control-unknown" role="status">
        <span className="muted">Run control status unavailable.</span>
      </div>
    ) : null;
  }

  if (!st.active) {
    return (
      <div className="control-bar control-idle" role="status">
        <span className="dot dot-idle" aria-hidden="true" />
        <span>No run is active.</span>
        <Link to="/launch">Launch a run</Link>
      </div>
    );
  }

  const id = st.run?.run_id ?? st.job?.run_ids?.[0] ?? null;
  return (
    <div className="control-bar control-active" role="status">
      <div className="control-line">
        <span className="dot dot-live" aria-hidden="true" />
        <strong>A run is active</strong>
        {id ? (
          <Link to={`/runs/${encodeURIComponent(id)}`} className="mono control-id">
            {id}
          </Link>
        ) : (
          <span className="muted">(starting, no run id yet)</span>
        )}
        {st.run?.state && <span className="muted">state: {st.run.state}</span>}
        {st.run?.pid != null && <span className="muted mono">pid {st.run.pid}</span>}
        <span className="control-spacer" />
        <button type="button" className="btn control-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Hide launch log" : "Launch log"}
        </button>
      </div>
      <div className="muted control-why">
        Launching, resuming, re-scoring and cleaning are disabled until this run ends: only one run can be managed at a time.
        {st.reason && <> Server: {st.reason}</>}
      </div>
      {open && (
        <pre className="log-tail" aria-label="Launch log tail">
          {st.log_tail ? st.log_tail : "(no log output yet)"}
        </pre>
      )}
    </div>
  );
}
