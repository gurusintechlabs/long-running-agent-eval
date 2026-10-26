import { useEffect } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ApiError, api, useAsync } from "../../api";
import { IngestButton, IngestResultView, useIngest } from "../../app/IngestBanner";
import { Card, ErrorState, Spinner } from "../../components";
import { CheckpointsTab } from "./checkpoints/CheckpointsTab";
import { isTab, type TabId } from "./common/links";
import { EventsTab } from "./events/EventsTab";
import { HazardList } from "./HazardList";
import { MetricCharts } from "./MetricCharts";
import { RunHeader } from "./RunHeader";
import { RunTabs } from "./RunTabs";
import { TestsTab } from "./tests/TestsTab";
import { TimelineTab } from "./timeline/TimelineTab";
import { TranscriptTab } from "./transcript/TranscriptTab";
import { SafetyPanel } from "../live";
import "./run-detail.css";
import "./run-detail-u3.css";
import { JudgesTab } from "./judges/JudgesTab";

const REFRESH_MS = 4000;

export function RunDetailView() {
  const { runId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab: TabId = isTab(params.get("tab")) ? (params.get("tab") as TabId) : "overview";
  const detailQ = useAsync((s) => api.run(runId, s), [runId], (d) => (d?.run.live ? REFRESH_MS : null));
  const cpQ = useAsync((s) => api.checkpoints(runId, s), [runId], () => (detailQ.data?.run.live ? REFRESH_MS : null));
  const ing = useIngest();

  useEffect(() => {
    document.title = `${runId} · LRAE`;
  }, [runId]);

  const selectTab = (t: TabId) => setParams(t === "overview" ? {} : { tab: t });

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
  const live = detail.run.live;

  return (
    <>
      {back}
      <RunHeader detail={detail} />
      <RunTabs active={tab} onSelect={selectTab} />

      <div id="run-tabpanel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="tabpanel">
        {tab === "overview" && (
          <>
            {!detail.run.ingested && (
              <Card>
                <div className="not-ingested">
                  <div>
                    <h2>Not ingested yet</h2>
                    <p className="muted">
                      This run is on disk but not in the metrics store, so per-checkpoint metrics, hazards, duration and time-to-first-hazard are not available.
                      The Timeline, Transcript, Events and Checkpoints tabs read the logs directly and still work.
                    </p>
                  </div>
                  <IngestButton running={ing.running} onClick={() => void ing.run()} />
                </div>
                <IngestResultView result={ing.result} failure={ing.failure} onDismiss={ing.dismiss} />
              </Card>
            )}

            <SafetyPanel runId={runId} live={live} />

            {detail.run.ingested &&
              (cpQ.error && !cpQ.data ? (
                <Card><ErrorState title="Could not load checkpoints" error={cpQ.error} onRetry={cpQ.reload} /></Card>
              ) : cps.some((c) => Object.keys(c.metrics).length > 0) ? (
                <MetricCharts checkpoints={cps} hazards={detail.hazards} />
              ) : null)}

            <HazardList hazards={detail.hazards} ingested={detail.run.ingested} runId={runId} />
          </>
        )}

        {tab === "timeline" && <TimelineTab runId={runId} live={live} />}
        {tab === "tests" && <TestsTab runId={runId} onReingest={() => void ing.run()} reingesting={ing.running} />}
        {tab === "judges" && <JudgesTab runId={runId} live={live} />}
        {tab === "transcript" && <TranscriptTab runId={runId} live={live} />}
        {tab === "events" && <EventsTab runId={runId} live={live} />}
        {tab === "checkpoints" && (
          <CheckpointsTab runId={runId} checkpoints={cps} ingested={ingested} loading={cpQ.loading} error={cpQ.data ? null : cpQ.error} onRetry={cpQ.reload} />
        )}
      </div>
    </>
  );
}
