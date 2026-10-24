import { useState } from "react";
import { api, controlApi, errInfo, useAsync, type ErrInfo, type PreviewResponse, type RunDetail } from "../../api";
import { useControlState } from "../../app/ControlBar";
import { useDataVersion } from "../../app/DataVersion";
import { Dialog, Spinner } from "../../components";
import { ActionError, JobOutput } from "./ActionResult";
import { CleanButton } from "./CleanDialog";
import { ConfirmPanel } from "./ConfirmPanel";
import { EstimateView } from "./EstimateView";
import { useAction } from "./useAction";
import "./launch.css";

type Which = "stop" | "kill" | "resume" | "score" | null;

/**
 * Control actions for one run, shown in the run header. Only actions valid for the run's state appear:
 * a live run can be stopped or killed; a finished/interrupted run can be resumed from a checkpoint or
 * re-scored; clean is global. Everything that starts something goes through a confirm dialog.
 */
export function RunActions({ detail }: { detail: RunDetail }) {
  const { run } = detail;
  const [which, setWhich] = useState<Which>(null);
  const ctl = useControlState();
  const { bump } = useDataVersion();
  const otherActive = ctl.data?.active === true && !run.live;
  const close = () => setWhich(null);
  const canResume = !run.live && run.checkpoints > 0 && run.state !== "COMPLETED";
  const canScore = !run.live && run.checkpoints > 0;
  const busyTitle = otherActive ? "Another run is active: only one run can be managed at a time" : undefined;

  return (
    <div className="run-actions" role="group" aria-label="Run actions">
      {run.live && (
        <>
          <button type="button" className="btn" onClick={() => setWhich("stop")}>
            Stop…
          </button>
          <button type="button" className="btn btn-danger-outline" onClick={() => setWhich("kill")}>
            Kill…
          </button>
        </>
      )}
      {canResume && (
        <button type="button" className="btn" disabled={otherActive} title={busyTitle} onClick={() => setWhich("resume")}>
          Resume…
        </button>
      )}
      {canScore && (
        <button type="button" className="btn" disabled={otherActive} title={busyTitle} onClick={() => setWhich("score")}>
          Re-score…
        </button>
      )}
      {!run.live && <CleanButton disabled={otherActive} />}

      {which === "stop" && <StopDialog runId={run.run_id} onClose={close} onDone={bump} />}
      {which === "kill" && <KillDialog runId={run.run_id} onClose={close} onDone={bump} />}
      {which === "resume" && <ResumeDialog runId={run.run_id} blocked={otherActive} onClose={close} onDone={bump} />}
      {which === "score" && <ScoreDialog runId={run.run_id} onClose={close} onDone={bump} />}
    </div>
  );
}

function StopDialog({ runId, onClose, onDone }: { runId: string; onClose: () => void; onDone: () => void }) {
  const act = useAction<Awaited<ReturnType<typeof controlApi.stop>>>();
  return (
    <Dialog
      title="Stop this run?"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {act.result ? "Close" : "Cancel"}
          </button>
          {!act.result && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={act.busy}
              onClick={() => void act.run(() => controlApi.stop(runId)).then((r) => r && onDone())}
            >
              {act.busy ? "Sending…" : "Stop run"}
            </button>
          )}
        </>
      }
    >
      <p className="mono">{runId}</p>
      <p>
        Stop sends a graceful interrupt (SIGINT) to the harness. It then finalizes: it terminates the agent, cleans up, writes the manifest end and finishes scoring of the
        checkpoints already queued.
      </p>
      <ul>
        <li>
          The run currently ends in state <strong>FAILED</strong> (that is what the runner records for an interrupt), with no error text. Snapshots taken so far stay valid, so you can resume from
          them.
        </li>
        <li>With a real judge, scoring of already-queued checkpoints can still spend after you press Stop.</li>
        <li>Finalizing takes a little while; the run page keeps updating. For an immediate hard stop use Kill.</li>
      </ul>
      {act.err && <ActionError err={act.err} />}
      {act.result && (
        <div className="issues issues-ok" role="status">
          <strong>
            {act.result.signalled} sent to pid {act.result.pid}.
          </strong>{" "}
          The run is finalizing.
        </div>
      )}
    </Dialog>
  );
}

function KillDialog({ runId, onClose, onDone }: { runId: string; onClose: () => void; onDone: () => void }) {
  const act = useAction<Awaited<ReturnType<typeof controlApi.kill>>>();
  const [typed, setTyped] = useState("");
  const ok = typed === runId;
  return (
    <Dialog
      title="Kill this run?"
      tone="danger"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {act.result ? "Close" : "Cancel"}
          </button>
          {!act.result && (
            <button
              type="button"
              className="btn btn-danger"
              disabled={!ok || act.busy}
              onClick={() => void act.run(() => controlApi.kill(runId, typed)).then((r) => r && onDone())}
            >
              {act.busy ? "Killing…" : "Kill run"}
            </button>
          )}
        </>
      }
    >
      <p>
        Kill sends SIGKILL to the harness: <strong>no cleanup runs</strong> and the in-flight work is lost. The server then runs <span className="mono">lrae clean</span>, which marks the run
        INTERRUPTED (recovered), reaps the agent and fixtures and restores user memory. Clean is global and also recovers other crashed runs. Prefer Stop unless the run is stuck.
      </p>
      <label className="lf-field">
        <span>
          Type the run id to confirm: <span className="mono">{runId}</span>
        </span>
        <input className="field mono" value={typed} autoComplete="off" onChange={(e) => setTyped(e.target.value)} />
      </label>
      {act.err && <ActionError err={act.err} />}
      {act.result && (
        <div className="issues issues-ok" role="status">
          <strong>
            {act.result.signalled} sent to pid {act.result.pid}.
          </strong>
          {act.result.clean && <JobOutput job={act.result.clean} label="Clean" />}
        </div>
      )}
    </Dialog>
  );
}

function ScoreDialog({ runId, onClose, onDone }: { runId: string; onClose: () => void; onDone: () => void }) {
  const cps = useAsync((s) => api.checkpoints(runId, s), [runId]);
  const [k, setK] = useState("");
  const act = useAction<Awaited<ReturnType<typeof controlApi.score>>>();
  return (
    <Dialog
      title="Re-score this run"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={act.busy}
            onClick={() => void act.run(() => controlApi.score(runId, k === "" ? undefined : Number(k))).then((r) => r && onDone())}
          >
            {act.busy ? "Starting…" : "Re-score"}
          </button>
        </>
      }
    >
      <p className="mono">{runId}</p>
      <p>
        Re-scoring runs <span className="mono">lrae score</span> on the saved snapshots and appends a new scoring pass; metrics are recomputed. It is refused while any run is active.
      </p>
      <p>
        <strong>Judge spend rule:</strong> it spends nothing when the run's spec uses a scripted judge. If the judge is <span className="mono">claude_code</span> the server answers
        409 <span className="mono">judge_spends</span> and starts nothing: re-scoring with a real judge can only be done from the terminal with an explicit spend confirmation.
      </p>
      <label className="lf-field">
        <span>Checkpoint</span>
        <select className="field" value={k} onChange={(e) => setK(e.target.value)}>
          <option value="">All checkpoints</option>
          {(cps.data?.checkpoints ?? []).map((c) => (
            <option key={c.k} value={c.k}>
              t{c.k}
            </option>
          ))}
        </select>
      </label>
      {act.err && <ActionError err={act.err} />}
      {act.result && <JobOutput job={act.result} label="Score" />}
    </Dialog>
  );
}

function ResumeDialog({ runId, blocked, onClose, onDone }: { runId: string; blocked: boolean; onClose: () => void; onDone: () => void }) {
  const cps = useAsync((s) => api.checkpoints(runId, s), [runId]);
  const [k, setK] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ErrInfo | null>(null);
  const [preview, setPreview] = useState<{ resp: PreviewResponse; at: number } | null>(null);
  const [started, setStarted] = useState<string | null>(null);
  const list = cps.data?.checkpoints ?? [];
  const from = k !== "" ? `t${k}` : "";

  async function doPreview() {
    if (!from) return;
    setBusy(true);
    setErr(null);
    setPreview(null);
    try {
      setPreview({ resp: await controlApi.resumePreview(runId, from), at: Date.now() });
    } catch (e) {
      setErr(errInfo(e));
    } finally {
      setBusy(false);
    }
  }

  const blockedReason = blocked
    ? "A run is active: resume is not allowed until it ends."
    : preview && !preview.resp.launch_allowed_now
      ? "The server says a start is not allowed right now."
      : preview && preview.resp.blockers.length
        ? "The preview has blockers."
        : null;

  return (
    <Dialog
      title="Resume from a checkpoint"
      tone={preview?.resp.estimate.real_spend ? "danger" : "default"}
      onClose={onClose}
      footer={
        <button type="button" className="btn" onClick={onClose}>
          {started ? "Close" : "Cancel"}
        </button>
      }
    >
      <p className="mono">{runId}</p>
      <p>
        Resume restores the workspace from a saved snapshot and continues the same run. The spec file must be unchanged (same hash). The server computes the estimate and issues a one-time
        confirmation, as for a launch.
      </p>
      {cps.loading ? (
        <Spinner label="Loading checkpoints" />
      ) : cps.error ? (
        <ActionError err={errInfo(cps.error)} />
      ) : (
        <label className="lf-field">
          <span>Resume from</span>
          <select
            className="field"
            value={k}
            onChange={(e) => {
              setK(e.target.value);
              setPreview(null);
              setErr(null);
            }}
          >
            <option value="">Select a checkpoint…</option>
            {list.map((c) => (
              <option key={c.k} value={c.k}>
                t{c.k}
                {c.head_sha ? ` (${c.head_sha.slice(0, 8)})` : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      <div>
        <button type="button" className="btn btn-primary" disabled={!from || busy || !!started} onClick={() => void doPreview()}>
          {busy ? "Previewing…" : "Preview resume"}
        </button>
      </div>
      {err && <ActionError err={err} />}
      {preview && !started && (
        <>
          <EstimateView preview={preview.resp} />
          <ConfirmPanel
            preview={preview.resp}
            receivedAt={preview.at}
            actionLabel="Resume"
            blockedReason={blockedReason}
            onRepreview={() => void doPreview()}
            onSubmit={async (typed, nonce) => {
              const r = await controlApi.resume(runId, from, nonce, typed);
              setStarted(r.run_id ?? runId);
              onDone();
            }}
          />
        </>
      )}
      {started && (
        <div className="issues issues-ok" role="status">
          <strong>Resume started.</strong> The run page will show it as live shortly.
        </div>
      )}
    </Dialog>
  );
}
