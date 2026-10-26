import { useCallback, useEffect, useState } from "react";
import { ApiError, compareApi, errInfo, useAsync, type RebuildResult, type ReportEntry, type ReportsResponse } from "../../api";
import { IngestButton, IngestResultView, useIngest } from "../../app/IngestBanner";
import { Badge, Card, EmptyState, ErrorState, Spinner } from "../../components";
import { ageLabel, formatDateTime } from "../../lib/format";
import { DashboardPreview, openBlob } from "./DashboardPreview";
import "./reports.css";

type Kind = "dashboard" | "pdf";
interface Building {
  exp: string;
  kind: Kind;
}

function size(n: number): string {
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} kB`;
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, []);
  return <span>{Math.floor((now - since) / 1000)}s</span>;
}

interface Outcome {
  kind: Kind;
  result?: RebuildResult;
  failure?: { message: string; output?: string };
  stale?: { reason: string };
}

function ReportCard({
  e,
  data,
  building,
  onBuild,
  onReload,
}: {
  e: ReportEntry;
  data: ReportsResponse;
  building: Building | null;
  onBuild: (exp: string, kind: Kind, allowStale: boolean) => Promise<Outcome>;
  onReload: () => void;
}) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [preview, setPreview] = useState(false);
  const [openErr, setOpenErr] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState(0);
  const ing = useIngest();
  const mine = building?.exp === e.experiment_id ? building : null;
  const busy = building != null;
  const chromeOk = data.chrome.available;

  const run = async (kind: Kind, allowStale = false) => {
    setOutcome(null);
    setStartedAt(Date.now());
    const o = await onBuild(e.experiment_id, kind, allowStale);
    setOutcome(o);
    if (o.result?.ok) onReload();
  };

  const reingestThenBuild = async (kind: Kind) => {
    await ing.run();
    await run(kind);
  };

  const openPdf = async () => {
    setOpenErr(null);
    try {
      await openBlob(compareApi.fileBlob(e.experiment_id, "report.pdf"), `${e.experiment_id}-report.pdf`);
    } catch (err) {
      setOpenErr(errInfo(err).message);
    }
  };

  return (
    <Card
      title={<span className="mono rp-title">{e.experiment_id}</span>}
      actions={
        <div className="row rp-badges">
          {!e.in_store && <Badge tone="warn" title="Not in the metrics store: cannot be rebuilt until ingested">not in store</Badge>}
          {e.older_than_store && <Badge tone="warn" title="The metrics store was updated after these files were built">older than the store</Badge>}
          {!e.has_reports && <Badge tone="neutral">no reports yet</Badge>}
        </div>
      }
    >
      <dl className="rp-files">
        <div>
          <dt>Dashboard</dt>
          <dd>{e.dashboard ? `${formatDateTime(e.dashboard.mtime)} · ${ageLabel(e.dashboard.mtime)} · ${size(e.dashboard.bytes)} · ${e.figures.length} figures` : "not built"}</dd>
        </div>
        <div>
          <dt>PDF</dt>
          <dd>{e.pdf ? `${formatDateTime(e.pdf.mtime)} · ${ageLabel(e.pdf.mtime)} · ${size(e.pdf.bytes)}` : "not built"}</dd>
        </div>
      </dl>

      <div className="row rp-actions">
        <button type="button" className="btn" disabled={!e.dashboard} onClick={() => setPreview((p) => !p)} aria-expanded={preview}>
          {preview ? "Hide dashboard" : "Open dashboard"}
        </button>
        <button type="button" className="btn" disabled={!e.pdf} onClick={() => void openPdf()}>
          Open PDF
        </button>
        <span className="rp-sep" aria-hidden="true" />
        <button type="button" className="btn btn-primary" disabled={busy || !e.in_store} onClick={() => void run("dashboard")}>
          {mine?.kind === "dashboard" ? "Rebuilding…" : "Rebuild dashboard"}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !e.in_store || !chromeOk}
          title={chromeOk ? undefined : (data.chrome.error ?? "headless Chrome not found")}
          onClick={() => void run("pdf")}
        >
          {mine?.kind === "pdf" ? "Rebuilding…" : "Rebuild PDF"}
        </button>
      </div>
      {!chromeOk && (
        <p className="rp-hint">
          <strong>PDF needs headless Chrome.</strong> {data.chrome.error ?? "Chrome not found."} Install Google Chrome or Chromium, or set <span className="mono">LRAE_CHROME</span> before starting{" "}
          <span className="mono">lrae ui</span>.
        </p>
      )}
      {openErr && <p className="rp-hint rp-bad" role="alert">{openErr}</p>}

      {mine && (
        <div className="rp-progress" role="status">
          <div className="spinner" aria-hidden="true" />
          <span>
            Running <span className="mono">{mine.kind === "pdf" ? `lrae report ${mine.exp} --pdf` : `lrae dashboard ${mine.exp}`}</span> · <Elapsed since={startedAt} />
            {mine.kind === "pdf" ? " (a PDF can take a minute)" : ""}
          </span>
        </div>
      )}

      {outcome?.stale && (
        <div className="rp-stale" role="alert">
          <p>
            <strong>The metrics store is out of date.</strong> {outcome.stale.reason}. A report built now would miss that data.
          </p>
          <div className="row">
            <IngestButton running={ing.running} onClick={() => void reingestThenBuild(outcome.kind)} label="Re-ingest, then rebuild" />
            <button type="button" className="btn" disabled={busy} onClick={() => void run(outcome.kind, true)}>
              Rebuild anyway
            </button>
          </div>
        </div>
      )}
      <IngestResultView result={ing.result} failure={ing.failure} onDismiss={ing.dismiss} />

      {outcome?.failure && (
        <div className="rp-fail" role="alert">
          <strong>{outcome.failure.message}</strong>
          {outcome.failure.output && <pre className="rp-tail">{outcome.failure.output}</pre>}
        </div>
      )}
      {outcome?.result && (
        <div className={outcome.result.ok ? "rp-ok" : "rp-fail"} role="status">
          <strong>
            {outcome.result.ok ? `Built ${outcome.result.kind === "pdf" ? "report.pdf" : "dashboard.html"} in ${outcome.result.duration_s}s.` : "Build failed."}
          </strong>
          {outcome.result.stale_store && <span className="muted"> Built from an out-of-date store (as you asked).</span>}
          {outcome.result.output && (
            <details open={!outcome.result.ok}>
              <summary>Output</summary>
              <pre className="rp-tail">{outcome.result.output}</pre>
            </details>
          )}
        </div>
      )}

      {preview && e.dashboard && <DashboardPreview experiment={e.experiment_id} figures={e.figures.map((f) => f.name)} builtAt={e.dashboard.mtime} />}
    </Card>
  );
}

export function ReportsView() {
  const q = useAsync((s) => compareApi.reports(s), []);
  const [building, setBuilding] = useState<Building | null>(null);
  const ing = useIngest();

  useEffect(() => {
    document.title = "Reports · LRAE";
  }, []);

  const onBuild = useCallback(async (exp: string, kind: Kind, allowStale: boolean): Promise<Outcome> => {
    setBuilding({ exp, kind });
    try {
      return { kind, result: await compareApi.rebuild(exp, kind, allowStale) };
    } catch (err) {
      const info = errInfo(err);
      if (info.status === 409 && info.code === "store_stale") return { kind, stale: { reason: info.message } };
      const body = err instanceof ApiError && err.body && typeof err.body === "object" ? (err.body as Record<string, unknown>) : null;
      if (body && typeof body.output === "string") {
        return { kind, result: { ok: false, kind, exit_code: typeof body.exit_code === "number" ? body.exit_code : null, output: body.output, artifact: null, duration_s: Number(body.duration_s ?? 0), stale_store: false } };
      }
      return { kind, failure: { message: info.code === "chrome_not_found" ? `Chrome not found: ${info.message}` : info.message } };
    } finally {
      setBuilding(null);
    }
  }, []);

  const data = q.data;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <div className="page-sub">Open or rebuild the static dashboard and the PDF report of an experiment. Costs in reports are estimated (API-equivalent), not a bill.</div>
        </div>
      </div>

      {q.loading && <Spinner label="Loading reports" />}
      {q.error && !data && (
        <Card>
          <ErrorState title="Could not load reports" error={q.error} onRetry={q.reload} />
        </Card>
      )}
      {data?.ingest.stale && (
        <Card className="card-warn">
          <div className="not-ingested">
            <div>
              <strong>The metrics store is out of date.</strong>
              <p className="muted">
                {data.ingest.reason}. Reports are built from the store, so re-ingest before rebuilding to include every run.
              </p>
            </div>
            <IngestButton running={ing.running} onClick={() => void ing.run().then(q.reload)} />
          </div>
          <IngestResultView result={ing.result} failure={ing.failure} onDismiss={ing.dismiss} />
        </Card>
      )}
      {data && data.experiments.length === 0 && (
        <Card>
          <EmptyState title="No experiments yet">Reports are built from the metrics store. Run an experiment and ingest it first.</EmptyState>
        </Card>
      )}
      {data?.experiments.map((e) => (
        <ReportCard key={e.experiment_id} e={e} data={data} building={building} onBuild={onBuild} onReload={q.reload} />
      ))}
    </>
  );
}
