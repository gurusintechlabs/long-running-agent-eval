import { useState } from "react";
import { api, useAsync, type IngestResult } from "../api";
import { useDataVersion } from "./DataVersion";
import "./app.css";

/** Re-ingest control, shared by the stale banner and the "not ingested yet" panels. */
export function useIngest() {
  const { bump } = useDataVersion();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setResult(null);
    setFailure(null);
    try {
      const r = await api.ingest();
      setResult(r);
      if (r.ok) bump();
    } catch (e) {
      setFailure(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };
  return { running, result, failure, run, dismiss: () => (setResult(null), setFailure(null)) };
}

export function IngestButton({ running, onClick, label = "Re-ingest now" }: { running: boolean; onClick: () => void; label?: string }) {
  return (
    <button type="button" className="btn btn-primary" onClick={onClick} disabled={running}>
      {running ? "Ingesting…" : label}
    </button>
  );
}

export function IngestResultView({ result, failure, onDismiss }: { result: IngestResult | null; failure: string | null; onDismiss: () => void }) {
  if (!result && !failure) return null;
  const ok = result?.ok === true;
  return (
    <div className={`ingest-result ${ok ? "ingest-ok" : "ingest-bad"}`} role="status">
      <div className="ingest-result-head">
        <strong>{ok ? "Ingest finished." : "Ingest failed."}</strong>
        <button type="button" className="btn" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
      {failure && <p>{failure}</p>}
      {result?.output && (
        <details open={!ok}>
          <summary>Output</summary>
          <pre>{result.output}</pre>
        </details>
      )}
    </div>
  );
}

/** Banner shown while metrics.sqlite is out of date with the logs on disk (working rule 5: logs win). */
export function IngestBanner() {
  const { version } = useDataVersion();
  const status = useAsync((s) => api.ingestStatus(s), [version], () => 15000);
  const ing = useIngest();
  const st = status.data;

  if (!st?.stale && !ing.result && !ing.failure && !ing.running) return null;

  return (
    <div className="banner-wrap">
      {(st?.stale || ing.running) && st && (
        <div className="banner banner-warn" role="status">
          <div>
            <strong>The metrics store is out of date.</strong>{" "}
            <span>
              {st.reason ?? "Stale"}. {st.runs_in_store} of {st.runs_on_disk} runs are ingested; the rest show no metrics or hazards until you
              re-ingest. Run lists and checkpoints still come straight from the logs.
            </span>
          </div>
          <IngestButton running={ing.running} onClick={() => void ing.run().then(status.reload)} />
        </div>
      )}
      <IngestResultView result={ing.result} failure={ing.failure} onDismiss={ing.dismiss} />
    </div>
  );
}
