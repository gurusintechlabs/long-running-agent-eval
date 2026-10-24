import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, api, useAsync } from "../../api";
import { useDataVersion } from "../../app/DataVersion";
import { IngestButton, IngestResultView, useIngest } from "../../app/IngestBanner";
import { Card, ErrorState, Spinner } from "../../components";
import { CheckpointsTable } from "./CheckpointsTable";
import { HazardList } from "./HazardList";
import { MetricCharts } from "./MetricCharts";
import { RunHeader } from "./RunHeader";
import "./run-detail.css";

const REFRESH_MS = 4000;

export function RunDetailView() {
  const { runId = "" } = useParams();
  const { version } = useDataVersion();
  const detailQ = useAsync((s) => api.run(runId, s), [runId, version], (d) => (d?.run.live ? REFRESH_MS : null));
  const cpQ = useAsync((s) => api.checkpoints(runId, s), [runId, version], () => (detailQ.data?.run.live ? REFRESH_MS : null));
  const ing = useIngest();

  useEffect(() => {
    document.title = `${runId} · LRAE`;
  }, [runId]);

  const back = (
    <Link to="/runs" className="back-link">
      {"←"} All runs
    </Link>
  );

  if (detailQ.error && !detailQ.data) {
    const notFound = detailQ.error instanceof ApiError && detailQ.error.status === 404;
    return (
      <>
        {back}
        <Card>
          <ErrorState title={notFound ? "No such run" : "Could not load this run"} error={notFound ? null : detailQ.error} onRetry={notFound ? undefined : detailQ.reload} />
        </Card>
      </>
    );
  }
  if (!detailQ.data) {
    return (
      <>
        {back}
        <Spinner label="Loading run" />
      </>
    );
  }

  const detail = detailQ.data;
  const cps = cpQ.data?.checkpoints ?? [];
  const ingested = cpQ.data?.ingested ?? detail.run.ingested;

  return (
    <>
      {back}
      <RunHeader detail={detail} />

      {!detail.run.ingested && (
        <Card>
          <div className="not-ingested">
            <div>
              <h2>Not ingested yet</h2>
              <p className="muted">
                This run is on disk but not in the metrics store, so per-checkpoint metrics, hazards, duration and time-to-first-hazard are not available.
                The checkpoint list below comes straight from the logs.
              </p>
            </div>
            <IngestButton running={ing.running} onClick={() => void ing.run()} />
          </div>
          <IngestResultView result={ing.result} failure={ing.failure} onDismiss={ing.dismiss} />
        </Card>
      )}

      {detail.run.ingested && (
        cpQ.error && !cpQ.data ? (
          <Card><ErrorState title="Could not load checkpoints" error={cpQ.error} onRetry={cpQ.reload} /></Card>
        ) : cps.some((c) => Object.keys(c.metrics).length > 0) ? (
          <MetricCharts checkpoints={cps} hazards={detail.hazards} />
        ) : null
      )}

      {cpQ.error && !cpQ.data && !detail.run.ingested ? (
        <Card><ErrorState title="Could not load checkpoints" error={cpQ.error} onRetry={cpQ.reload} /></Card>
      ) : cpQ.loading ? (
        <Spinner label="Loading checkpoints" />
      ) : (
        <CheckpointsTable checkpoints={cps} ingested={ingested} />
      )}

      <HazardList hazards={detail.hazards} ingested={detail.run.ingested} />
    </>
  );
}
