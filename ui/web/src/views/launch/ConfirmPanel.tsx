import { useEffect, useId, useState } from "react";
import { errInfo, type ConfirmTyped, type ErrInfo, type PreviewResponse } from "../../api";
import { formatUsd } from "../../lib/format";

/** Seconds left until the nonce expires (counts down once a second). */
export function useCountdown(receivedAt: number, expiresInS: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);
  return Math.max(0, Math.ceil((receivedAt + expiresInS * 1000 - now) / 1000));
}

/** "10", "$10", "10.00" -> 10; anything else -> NaN. Only used to enable the button; the server decides. */
export function parseTyped(s: string): number {
  const t = s.trim().replace(/^\$/, "");
  if (!/^\d+(\.\d+)?$/.test(t)) return NaN;
  return Number(t);
}

export function fmtClock(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Error codes after which the nonce is gone: the user must preview again. */
const DEAD_NONCE = new Set(["nonce_invalid", "spec_changed"]);

/**
 * The typed-confirmation gate. For real spend the user types the two figures (never prefilled); for
 * scripted runs the dialog itself is the confirmation. The submit button is disabled until the typed
 * values equal the server's `confirmation.fields`, the nonce is alive and nothing blocks the start.
 */
export function ConfirmPanel({
  preview,
  receivedAt,
  actionLabel,
  onSubmit,
  onRepreview,
  blockedReason,
}: {
  preview: PreviewResponse;
  receivedAt: number;
  actionLabel: string;
  onSubmit: (typed: ConfirmTyped, nonce: string) => Promise<void>;
  onRepreview: () => void;
  /** Non-null while a start is not allowed (a run is active, a blocker exists). */
  blockedReason: string | null;
}) {
  const left = useCountdown(receivedAt, preview.expires_in_s);
  const [usd, setUsd] = useState("");
  const [runs, setRuns] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ErrInfo | null>(null);
  const [dead, setDead] = useState(false);
  const usdId = useId();
  const runsId = useId();

  const nonce = preview.confirmation_nonce;
  const real = preview.estimate.real_spend || preview.confirmation.required;
  const fields = preview.confirmation.fields;
  const expired = left <= 0;
  const typedOk = !real || (!!fields && parseTyped(usd) === fields.confirm_usd && parseTyped(runs) === fields.confirm_runs);
  const canGo = !!nonce && !expired && !dead && !busy && !blockedReason && typedOk && (!real || !!fields);

  async function go() {
    if (!canGo || !nonce) return;
    setBusy(true);
    setErr(null);
    try {
      const typed: ConfirmTyped = real && fields ? { confirm_usd: parseTyped(usd), confirm_runs: parseTyped(runs) } : {};
      await onSubmit(typed, nonce);
    } catch (e) {
      const info = errInfo(e);
      setErr(info);
      if (info.code && DEAD_NONCE.has(info.code)) setDead(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className={`confirm-panel ${real ? "confirm-real" : ""}`}
      onSubmit={(ev) => {
        ev.preventDefault();
        void go();
      }}
    >
      {real && fields && (
        <>
          <p className="confirm-warn">
            <strong>Real money.</strong> To confirm, type the figures from the estimate above yourself (they are not filled in for you).
            {preview.confirmation.message && <span className="muted"> Server note: {preview.confirmation.message}</span>}
          </p>
          <div className="confirm-fields">
            <label htmlFor={usdId}>
              Maximum spend in USD
              <input id={usdId} className="field mono" inputMode="decimal" autoComplete="off" value={usd} onChange={(e) => setUsd(e.target.value)} aria-describedby={`${usdId}-h`} />
              <span id={`${usdId}-h`} className="muted">type the Max spend figure</span>
            </label>
            <label htmlFor={runsId}>
              Number of runs
              <input id={runsId} className="field mono" inputMode="numeric" autoComplete="off" value={runs} onChange={(e) => setRuns(e.target.value)} aria-describedby={`${runsId}-h`} />
              <span id={`${runsId}-h`} className="muted">type the Runs figure</span>
            </label>
          </div>
        </>
      )}
      {!real && <p>Scripted run: nothing is spent. Confirm to start it.</p>}

      <div className="confirm-status" role="status">
        {!nonce ? (
          <span className="status-bad">No confirmation was issued (see blockers above).</span>
        ) : dead ? (
          <span className="status-bad">This preview is no longer valid. Preview again to get a new confirmation.</span>
        ) : expired ? (
          <span className="status-bad">The confirmation expired (300 s limit). Preview again.</span>
        ) : (
          <span className="muted">
            Confirmation valid for <strong className="mono">{fmtClock(left)}</strong>
          </span>
        )}
        {blockedReason && <span className="status-bad">{blockedReason}</span>}
      </div>

      {err && (
        <div className="issues issues-bad" role="alert">
          <strong>
            {err.status ? `HTTP ${err.status}` : "Error"}
            {err.code ? ` ${err.code}` : ""}
          </strong>
          <div>{err.message}</div>
          {typeof err.extra.log_tail === "string" && <pre className="log-tail">{err.extra.log_tail}</pre>}
        </div>
      )}

      <div className="confirm-actions">
        {(expired || dead || !nonce) && (
          <button type="button" className="btn btn-primary" onClick={onRepreview}>
            Preview again
          </button>
        )}
        <button type="submit" className={`btn ${real ? "btn-danger" : "btn-primary"}`} disabled={!canGo}>
          {busy ? "Starting…" : real ? `${actionLabel} (real spend, up to ${formatUsd(preview.estimate.max_spend_usd)})` : actionLabel}
        </button>
      </div>
    </form>
  );
}
