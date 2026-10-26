import { useEffect, useRef, useState } from "react";
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

const STATUS_POLL_MS = 5000;

/**
 * Keeps every open view in step with metrics.sqlite. When the store file changes (the server's
 * auto-ingest or anyone's re-ingest finished), bump the data version: views re-fetch in the background
 * and keep showing their data meanwhile, so there is nothing to refresh by hand.
 */
function useStoreFollow(storeEpoch: number | null | undefined) {
  const { bump } = useDataVersion();
  const seen = useRef<number | null | undefined>(undefined);
  useEffect(() => {
    if (storeEpoch === undefined) return;
    if (seen.current !== undefined && storeEpoch !== seen.current) bump();
    seen.current = storeEpoch;
  }, [storeEpoch, bump]);
}

/**
 * With auto-ingest (the default for `lrae ui`) this shows only when the background ingest failed. Without
 * it (`lrae ui --no-auto-ingest` or an older server) it is the stale-store banner with the re-ingest
 * button (working rule 5: logs win).
 */
export function IngestBanner() {
  const status = useAsync((s) => api.ingestStatus(s), [], () => STATUS_POLL_MS);
  const ing = useIngest();
  const st = status.data;
  useStoreFollow(st?.store_epoch);

  const auto = st?.auto?.enabled === true;
  const autoFailed = auto && st?.auto?.last_ok === false;
  const showStale = !!st && ((st.stale && !auto) || autoFailed);
  if (!showStale && !ing.result && !ing.failure && !ing.running) return null;

  return (
    <div className="banner-wrap">
      {autoFailed && st && (
        <div className="banner banner-warn" role="status">
          <div>
            <strong>Updating the metrics store failed.</strong>{" "}
            <span>
              The server re-ingests by itself when new scores land; the last attempt failed. {st.runs_in_store} of {st.runs_on_disk} runs are in
              the store. It tries again when the logs change, or you can retry now.
            </span>
            {st.auto?.last_error && (
              <details>
                <summary>Output</summary>
                <pre>{st.auto.last_error}</pre>
              </details>
            )}
          </div>
          <IngestButton running={ing.running} label="Retry now" onClick={() => void ing.run().then(status.reload)} />
        </div>
      )}
      {!auto && (st?.stale || ing.running) && st && (
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
