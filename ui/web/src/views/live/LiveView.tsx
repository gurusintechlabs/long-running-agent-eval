import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiAuthError, ApiError } from "../../api";
import { Badge, Card, ErrorState, Spinner } from "../../components";
import { FeedPanel } from "./FeedPanel";
import { liveApi } from "./liveApi";
import { Overview } from "./Overview";
import { RunPicker } from "./RunPicker";
import { SafetyPanel } from "./SafetyPanel";
import { StatusStrip } from "./StatusStrip";
import type { LiveSnapshot } from "./types";
import { useFeed, type FeedMode } from "./useFeed";
import "./live.css";

const POLL_MS = 2000;

/** Route entry: `/live` (picker or the one active run), `/live/:runId` and `/runs/:runId/live`. */
export function LiveView() {
  const { runId } = useParams();
  if (!runId) return <RunPicker />;
  return <LivePage key={runId} runId={runId} />;
}

interface Snap {
  snap: LiveSnapshot;
  at: number;
}

/** Polls /live without ever blanking the data it already has (a reload must not remount the feed). */
function useSnapshot(runId: string) {
  const [data, setData] = useState<Snap | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [kick, setKick] = useState(0);
  const have = useRef(false);
  useEffect(() => {
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      try {
        const snap = await liveApi.live(runId, ctl.signal);
        if (ctl.signal.aborted) return;
        have.current = true;
        setData({ snap, at: Date.now() });
        setError(null);
        if (snap.live || snap.checkpoints.scoring.in_flight.length > 0) timer = setTimeout(run, POLL_MS);
      } catch (e) {
        if (ctl.signal.aborted) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        if (have.current && !(e instanceof ApiAuthError)) timer = setTimeout(run, 5000);
      }
    };
    void run();
    return () => {
      ctl.abort();
      if (timer) clearTimeout(timer);
    };
  }, [runId, kick]);
  return { data, error, refresh: () => setKick((k) => k + 1), retry: () => { have.current = false; setKick((k) => k + 1); } };
}

function LivePage({ runId }: { runId: string }) {
  const q = useSnapshot(runId);
  // The mode is decided once, from the first answer: a live run that ends keeps its feed on screen.
  const mode = useRef<FeedMode | null>(null);
  if (mode.current === null && q.data) mode.current = q.data.snap.live ? "live" : "replay";

  useEffect(() => {
    document.title = `${mode.current === "replay" ? "Replay" : "Live"} ${runId} · LRAE`;
  }, [runId, q.data]);

  if (q.error && !q.data) {
    const notFound = q.error instanceof ApiError && q.error.status === 404;
    return (
      <>
        <Link to="/live" className="back-link">{"←"} Live</Link>
        <Card><ErrorState title={notFound ? "No such run" : "Could not load this run"} error={notFound ? null : q.error} onRetry={notFound ? undefined : q.retry} /></Card>
      </>
    );
  }
  if (!q.data || !mode.current) return <Spinner label="Loading run" />;
  return <LiveBody runId={runId} mode={mode.current} data={q.data} onEnded={q.refresh} />;
}

function LiveBody({ runId, mode, data, onEnded }: { runId: string; mode: FeedMode; data: Snap; onEnded: () => void }) {
  const { snap, at } = data;
  const replay = mode === "replay";
  const [debug, setDebug] = useState(false);
  const handle = useFeed({ runId, mode, debug });

  // When the stream announces the end, refresh the snapshot once more (final state, final scoring).
  const endedSeen = useRef(false);
  useEffect(() => {
    if ((handle.ending || handle.ended) && !endedSeen.current) {
      endedSeen.current = true;
      onEnded();
    }
  }, [handle.ending, handle.ended, onEnded]);

  const live = !replay && snap.live && !handle.ended;
  return (
    <div className="lv">
      <div className="page-head">
        <div>
          <Link to={`/runs/${encodeURIComponent(runId)}`} className="back-link">{"←"} Run detail</Link>
          <h1 className="lv-h1">
            <span>{replay ? "Replay" : "Live"}</span> <span className="mono lv-id">{runId}</span>
          </h1>
          <div className="page-sub">
            {replay
              ? "A finished run, read from its logs from the start. Nothing is running."
              : "Following the run's logs as they are written. The UI only reads; it cannot affect the agent."}
          </div>
        </div>
        <div className="row">
          {live ? <Badge tone="ok" live>live</Badge> : <Badge tone="neutral" plain>{replay ? "replay" : "ended"}</Badge>}
        </div>
      </div>

      <StatusStrip snap={snap} fetchedAt={at} replay={replay} />
      {snap.catching_up && <div className="fc-note muted">The server is still reading a large log; figures may be partial for a moment.</div>}
      <Overview snap={snap} />

      <div className="lv-grid">
        <FeedPanel runId={runId} handle={handle} replay={replay} debug={debug} onDebug={setDebug} />
        <aside className="lv-side" id="safety" aria-label="Safety panel">
          <div className="lv-side-head">
            <h2>Safety</h2>
          </div>
          <SafetyPanel runId={runId} live={live} refreshKey={handle.incidentTick} />
        </aside>
      </div>
    </div>
  );
}
