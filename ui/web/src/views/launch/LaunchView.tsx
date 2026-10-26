import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { controlApi, errInfo, useAsync, type ErrInfo, type LaunchRequest, type PreviewResponse, type ControlSpecEntry } from "../../api";
import { useControlState } from "../../app/ControlBar";
import { Badge, Card, Dialog, ErrorState, Spinner } from "../../components";
import { formatUsd } from "../../lib/format";
import { CleanButton } from "./CleanDialog";
import { ConfirmPanel } from "./ConfirmPanel";
import { EstimateView } from "./EstimateView";
import "./launch.css";

/** "A, B" -> ["A","B"]; blank -> undefined. */
export function parseConfig(s: string): string | string[] | undefined {
  const parts = s.split(",").map((x) => x.trim()).filter(Boolean);
  if (!parts.length) return undefined;
  return parts.length === 1 ? parts[0] : parts;
}

/** "0, 1" -> [0,1]; blank -> undefined; junk -> null (invalid). */
export function parseRepeat(s: string): number | number[] | undefined | null {
  const parts = s.split(",").map((x) => x.trim()).filter(Boolean);
  if (!parts.length) return undefined;
  if (!parts.every((p) => /^\d+$/.test(p))) return null;
  const nums = parts.map(Number);
  return nums.length === 1 ? nums[0] : nums;
}

function SpecOption({ s }: { s: ControlSpecEntry }) {
  return (
    <option value={s.path} disabled={!s.valid}>
      {s.name}
      {s.runtime ? ` [${s.runtime}]` : ""}
      {s.valid ? "" : " (invalid, fix in Specs)"}
    </option>
  );
}

export function LaunchView() {
  const navigate = useNavigate();
  const specsQ = useAsync((s) => controlApi.specs(s), []);
  const ctl = useControlState();
  const [specPath, setSpecPath] = useState("");
  const [config, setConfig] = useState("");
  const [repeat, setRepeat] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [previewErr, setPreviewErr] = useState<ErrInfo | null>(null);
  const [preview, setPreview] = useState<{ resp: PreviewResponse; at: number } | null>(null);
  const [dialog, setDialog] = useState(false);
  const [waiting, setWaiting] = useState<{ log?: string } | null>(null);

  const specs =specsQ.data?.specs ?? [];
  const examples = specs.filter((s) => s.source === "example");
  const drafts = specs.filter((s) => s.source === "draft");
  const chosen = specs.find((s) => s.path === specPath) ?? null;
  const active = ctl.data?.active === true;
  const repeatParsed = parseRepeat(repeat);

  useEffect(() => {
    document.title = "Launch · LRAE";
  }, []);

  // Any edit to the selection invalidates the shown preview (the nonce is bound to the exact selection).
  function edit(fn: () => void) {
    fn();
    setPreview(null);
    setPreviewErr(null);
    setDialog(false);
  }

  async function doPreview() {
    if (!specPath || repeatParsed === null) return;
    setPreviewing(true);
    setPreviewErr(null);
    setPreview(null);
    setDialog(false);
    const req: LaunchRequest = { spec_path: specPath };
    const c = parseConfig(config);
    if (c !== undefined) req.config = c;
    if (repeatParsed !== undefined) req.repeat = repeatParsed;
    try {
      const resp = await controlApi.launchPreview(req);
      setPreview({ resp, at: Date.now() });
    } catch (e) {
      setPreviewErr(errInfo(e));
    } finally {
      setPreviewing(false);
    }
  }

  const blockedReason = useMemo(() => {
    if (!preview) return null;
    if (active) return "A run is active: launch is not allowed until it ends.";
    if (!preview.resp.launch_allowed_now) return "The server says a launch is not allowed right now.";
    if (preview.resp.blockers.length) return "The preview has blockers.";
    return null;
  }, [preview, active]);

  async function submitLaunch(typed: { confirm_usd?: number; confirm_runs?: number }, nonce: string) {
    const r = await controlApi.launch(nonce, typed);
    setDialog(false);
    if (r.manifest_seen && r.run_id) {
      navigate(`/runs/${encodeURIComponent(r.run_id)}`);
    } else {
      setWaiting({ log: r.log });
    }
  }

  if (waiting) return <WaitForRun onDone={(id) => navigate(`/runs/${encodeURIComponent(id)}`)} onBack={() => setWaiting(null)} />;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Launch</h1>
          <div className="page-sub">Pick a spec, preview the server-computed estimate, then confirm. One run at a time.</div>
        </div>
        <CleanButton disabled={active} />
      </div>

      {active && (
        <div className="issues issues-warn" role="status">
          <strong>Launch is not allowed while a run is active.</strong>
          <div>
            Only one run can be managed at a time.{" "}
            {ctl.data?.run?.run_id ? (
              <>
                Active run: <Link to={`/runs/${encodeURIComponent(ctl.data.run.run_id)}`} className="mono">{ctl.data.run.run_id}</Link>.
              </>
            ) : (
              "The active run has no id yet."
            )}{" "}
            You can still preview a spec; the Launch button stays disabled until the run ends.
          </div>
        </div>
      )}

      <Card
        title="1. Choose a spec"
        actions={
          <Link to="/specs" className="muted">
            Open the Specs editor
          </Link>
        }
      >
        {specsQ.loading ? (
          <Spinner label="Loading specs" />
        ) : specsQ.error ? (
          <ErrorState title="Could not load the spec list" error={specsQ.error} onRetry={specsQ.reload} />
        ) : specs.length === 0 ? (
          <p className="muted">No specs found. Create one in the Specs editor.</p>
        ) : (
          <div className="launch-form">
            <label className="lf-field">
              <span>Spec</span>
              <select className="field" value={specPath} onChange={(e) => edit(() => setSpecPath(e.target.value))}>
                <option value="">Select a spec…</option>
                {examples.length > 0 && (
                  <optgroup label="Examples">
                    {examples.map((s) => (
                      <SpecOption key={s.path} s={s} />
                    ))}
                  </optgroup>
                )}
                {drafts.length > 0 && (
                  <optgroup label="Drafts">
                    {drafts.map((s) => (
                      <SpecOption key={s.path} s={s} />
                    ))}
                  </optgroup>
                )}
              </select>
            </label>
            <label className="lf-field">
              <span>Config (optional)</span>
              <input className="field mono" value={config} placeholder="all configs, or e.g. A or A,B" onChange={(e) => edit(() => setConfig(e.target.value))} />
            </label>
            <label className="lf-field">
              <span>Repeat (optional)</span>
              <input className="field mono" value={repeat} placeholder="all repeats, or e.g. 0 or 0,1" aria-invalid={repeatParsed === null} onChange={(e) => edit(() => setRepeat(e.target.value))} />
              {repeatParsed === null && <span className="status-bad">Use whole numbers separated by commas.</span>}
            </label>
          </div>
        )}
        {chosen && (
          <div className="chosen-spec">
            <span className="mono">{chosen.path}</span>
            {chosen.runtime && (
              <Badge tone={chosen.runtime === "claude_code" ? "bad" : "ok"} plain>
                {chosen.runtime === "claude_code" ? "claude_code: real spend" : `${chosen.runtime}: no spend`}
              </Badge>
            )}
            {chosen.model && <span className="muted mono">{chosen.model}</span>}
            {chosen.experiment_id && <span className="muted">{chosen.experiment_id}</span>}
          </div>
        )}
        <div className="lf-actions">
          <button type="button" className="btn btn-primary" onClick={() => void doPreview()} disabled={!specPath || repeatParsed === null || previewing}>
            {previewing ? "Previewing…" : "Preview estimate"}
          </button>
          <span className="muted">Preview computes the estimate on the server. It starts nothing and spends nothing.</span>
        </div>
        {previewErr && (
          <div className="issues issues-bad" role="alert">
            <strong>
              Preview failed: HTTP {previewErr.status}
              {previewErr.code ? ` ${previewErr.code}` : ""}
            </strong>
            <div>{previewErr.message}</div>
          </div>
        )}
      </Card>

      {preview && (
        <Card title="2. Estimate (computed by the server)">
          <EstimateView preview={preview.resp} />
          <div className="lf-actions">
            <button
              type="button"
              className={`btn ${preview.resp.estimate.real_spend ? "btn-danger" : "btn-primary"}`}
              onClick={() => setDialog(true)}
              disabled={!preview.resp.confirmation_nonce}
            >
              Review and {preview.resp.estimate.real_spend ? "confirm real-spend launch" : "launch"}…
            </button>
            <span className="muted">Nothing starts until you confirm in the next step.</span>
          </div>
        </Card>
      )}

      {dialog && preview && (
        <Dialog
          title={preview.resp.estimate.real_spend ? "Confirm real-spend launch" : "Confirm launch"}
          tone={preview.resp.estimate.real_spend ? "danger" : "default"}
          onClose={() => setDialog(false)}
          closeLabel="Cancel"
        >
          <p>
            <span className="mono">{preview.resp.estimate.experiment_id}</span>: {preview.resp.estimate.run_count} run
            {preview.resp.estimate.run_count === 1 ? "" : "s"}, runtime <strong>{preview.resp.estimate.runtime}</strong>
            {preview.resp.estimate.real_spend && (
              <>
                , max spend <strong>{formatUsd(preview.resp.estimate.max_spend_usd)}</strong>
              </>
            )}
            .
          </p>
          <ConfirmPanel
            preview={preview.resp}
            receivedAt={preview.at}
            actionLabel="Launch"
            blockedReason={blockedReason}
            onSubmit={submitLaunch}
            onRepreview={() => void doPreview()}
          />
          <div>
            <button type="button" className="btn" onClick={() => setDialog(false)}>
              Cancel
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}

/** 202 case: the process is alive but its manifest has not appeared yet. Keep polling the control state. */
function WaitForRun({ onDone, onBack }: { onDone: (id: string) => void; onBack: () => void }) {
  const q = useControlState();
  const st = q.data;
  const id = st?.run?.run_id ?? null;
  useEffect(() => {
    if (id) onDone(id);
  }, [id, onDone]);
  const exited = st && !st.active && st.job && !st.job.alive;
  return (
    <>
      <div className="page-head">
        <h1>Launch</h1>
      </div>
      <Card title="Waiting for the run to appear">
        {exited ? (
          <div className="issues issues-bad" role="alert">
            <strong>The launch process ended without a run (exit code {String(st?.job?.exit_code)}).</strong>
            {st?.log_tail && <pre className="log-tail">{st.log_tail}</pre>}
            <button type="button" className="btn" onClick={onBack}>
              Back to Launch
            </button>
          </div>
        ) : (
          <>
            <p>
              The harness was started but has not written its manifest yet (this can take up to a minute). This page keeps checking the control state and opens the run
              when it appears.
            </p>
            <Spinner label="Waiting for the run" />
            {st?.log_tail && <pre className="log-tail">{st.log_tail}</pre>}
          </>
        )}
      </Card>
    </>
  );
}
