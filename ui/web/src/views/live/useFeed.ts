import { useCallback, useEffect, useRef, useState } from "react";
import { liveApi } from "./liveApi";
import { applyEvents, DEFAULT_CAP, emptyFeed, type FeedState } from "./feedStore";
import { followStream, type StreamStatus } from "./streamClient";
import type { DisplayEvent, StreamFrame } from "./types";

export type FeedMode = "live" | "replay";
export type FeedStatus = StreamStatus | "replay-loading" | "replay-ready" | "replay-error";

export interface FeedOptions {
  runId: string;
  mode: FeedMode;
  debug?: boolean;
  cap?: number;
  /** Events requested for the live backlog (server cap 2000). */
  backlog?: number;
  /** Replay page size. */
  pageSize?: number;
  /** Batch window for state updates, ms. */
  flushMs?: number;
}

export interface FeedHandle {
  feed: FeedState;
  status: FeedStatus;
  attempt: number;
  caughtUp: boolean;
  /** Set by run.ended / run.ending. */
  ending: { state?: string } | null;
  ended: { state?: string; crashed?: boolean; scoring_complete?: boolean } | null;
  /** Bumped when a guardrail / kill / budget event arrives after the backlog: refresh /safety. */
  incidentTick: number;
  /** Replay: nothing more on disk. */
  atEnd: boolean;
  loadingMore: boolean;
  loadMore: () => void;
  restart: () => void;
  error: string | null;
}

const INCIDENT_KINDS = new Set(["guardrail", "kill", "budget"]);

export function useFeed(o: FeedOptions): FeedHandle {
  const { runId, mode, debug = false, cap = DEFAULT_CAP, backlog = 300, pageSize = 400, flushMs = 120 } = o;
  const [feed, setFeed] = useState<FeedState>(emptyFeed);
  const [status, setStatus] = useState<FeedStatus>("connecting");
  const [attempt, setAttempt] = useState(0);
  const [caughtUp, setCaughtUp] = useState(false);
  const [ending, setEnding] = useState<{ state?: string } | null>(null);
  const [ended, setEnded] = useState<FeedHandle["ended"]>(null);
  const [incidentTick, setIncidentTick] = useState(0);
  const [atEnd, setAtEnd] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);

  const stateRef = useRef<FeedState>(emptyFeed());
  const pending = useRef<DisplayEvent[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const caughtRef = useRef(false);
  const nextCursor = useRef<string | null>(null);
  const loadingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const capRef = useRef(cap);
  capRef.current = cap;

  const flush = useCallback(() => {
    timer.current = null;
    if (pending.current.length === 0) return;
    const batch = pending.current;
    pending.current = [];
    stateRef.current = applyEvents(stateRef.current, batch, capRef.current);
    setFeed(stateRef.current);
  }, []);

  const enqueue = useCallback(
    (evs: DisplayEvent[], immediate = false) => {
      pending.current.push(...evs);
      if (immediate) {
        if (timer.current) clearTimeout(timer.current);
        flush();
      } else if (!timer.current) timer.current = setTimeout(flush, flushMs);
    },
    [flush, flushMs],
  );

  // (re)start whenever the run, the mode, the debug flag or the manual epoch changes
  useEffect(() => {
    const ctl = new AbortController();
    abortRef.current = ctl;
    stateRef.current = emptyFeed();
    pending.current = [];
    caughtRef.current = false;
    nextCursor.current = null;
    setFeed(stateRef.current);
    setCaughtUp(false);
    setEnding(null);
    setEnded(null);
    setAtEnd(false);
    setError(null);
    setAttempt(0);
    if (!runId) return;

    if (mode === "live") {
      setStatus("connecting");
      void followStream({
        runId,
        signal: ctl.signal,
        params: { from: "tail", backlog, level: debug ? "debug" : "info", fold: true, follow: true },
        onStatus: (s, info) => {
          setStatus(s);
          setAttempt(info?.attempt ?? 0);
        },
        onReset: () => {
          pending.current = [];
          stateRef.current = emptyFeed();
          setFeed(stateRef.current);
        },
        onFrame: (f: StreamFrame) => {
          switch (f.event) {
            case "ev": {
              enqueue([f.data]);
              if (caughtRef.current && INCIDENT_KINDS.has(f.data.kind) && f.data.severity !== "info") setIncidentTick((t) => t + 1);
              break;
            }
            case "caught-up":
              caughtRef.current = true;
              setCaughtUp(true);
              flush();
              break;
            case "run.ending":
              setEnding({ state: f.data.state });
              setIncidentTick((t) => t + 1);
              break;
            case "run.ended":
              setEnded({ state: f.data.state, crashed: f.data.crashed, scoring_complete: f.data.scoring_complete });
              setCaughtUp(true);
              setIncidentTick((t) => t + 1);
              flush();
              break;
            default:
              break;
          }
        },
      });
    } else {
      setStatus("replay-loading");
      loadingRef.current = true;
      setLoadingMore(true);
      liveApi
        .feedPage(runId, { from: "start", limit: pageSize, level: debug ? "debug" : "info" }, ctl.signal)
        .then((p) => {
          if (ctl.signal.aborted) return;
          nextCursor.current = p.next_cursor ?? null;
          enqueue(p.events, true);
          setAtEnd(!!p.at_end || !p.next_cursor || p.events.length === 0);
          setStatus("replay-ready");
          setCaughtUp(true);
        })
        .catch((e: unknown) => {
          if (ctl.signal.aborted) return;
          setError(e instanceof Error ? e.message : String(e));
          setStatus("replay-error");
        })
        .finally(() => {
          loadingRef.current = false;
          if (!ctl.signal.aborted) setLoadingMore(false);
        });
    }
    return () => {
      ctl.abort();
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
    };
  }, [runId, mode, debug, epoch, backlog, pageSize, enqueue, flush]);

  const loadMore = useCallback(() => {
    const ctl = abortRef.current;
    if (mode !== "replay" || !ctl || loadingRef.current || !nextCursor.current) return;
    loadingRef.current = true;
    setLoadingMore(true);
    liveApi
      .feedPage(runId, { from: nextCursor.current, limit: pageSize, level: debug ? "debug" : "info" }, ctl.signal)
      .then((p) => {
        if (ctl.signal.aborted) return;
        nextCursor.current = p.next_cursor ?? nextCursor.current;
        enqueue(p.events, true);
        if (p.at_end || p.events.length === 0) setAtEnd(true);
      })
      .catch((e: unknown) => {
        if (!ctl.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        loadingRef.current = false;
        if (!ctl.signal.aborted) setLoadingMore(false);
      });
  }, [mode, runId, pageSize, debug, enqueue]);

  const restart = useCallback(() => setEpoch((n) => n + 1), []);

  return { feed, status, attempt, caughtUp, ending, ended, incidentTick, atEnd, loadingMore, loadMore, restart, error };
}
