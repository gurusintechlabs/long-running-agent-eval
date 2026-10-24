import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "../../components";
import { FeedCard } from "./FeedCard";
import { buildRows, countBySource, type FeedFilters, type FeedRow, type FeedState, type MinSeverity } from "./feedStore";
import { Icon } from "./icons";
import type { FeedHandle } from "./useFeed";
import { VirtualList, type VirtualHandle } from "./VirtualList";

export const SOURCE_LABEL: Record<string, string> = {
  agent_stream: "Agent",
  orchestrator: "Run",
  guardrail: "Guardrails",
  counterpart: "Counterpart",
  env: "Environment",
  scorer: "Scorer",
  otel: "Telemetry",
};
const SOURCE_ORDER = Object.keys(SOURCE_LABEL);

function statusBadge(h: FeedHandle, replay: boolean) {
  if (replay) {
    if (h.status === "replay-error") return <Badge tone="bad">load failed</Badge>;
    return null;
  }
  switch (h.status) {
    case "open":
      return h.ended ? <Badge tone="neutral">ended</Badge> : h.caughtUp ? <Badge tone="ok" live>live</Badge> : <Badge tone="info" live>catching up</Badge>;
    case "connecting":
      return <Badge tone="info" live>connecting</Badge>;
    case "reconnecting":
      return (
        <Badge tone="warn" live title="The stream dropped; resuming from the last event with no gaps.">
          reconnecting{h.attempt > 1 ? ` (try ${h.attempt})` : ""}
        </Badge>
      );
    case "ended":
      return <Badge tone="neutral">ended</Badge>;
    case "unauthorized":
      return <Badge tone="bad">not authorised</Badge>;
    case "failed":
      return <Badge tone="bad">stream unavailable</Badge>;
    default:
      return null;
  }
}

export function FeedPanel({
  runId,
  handle,
  replay,
  debug,
  onDebug,
}: {
  runId: string;
  handle: FeedHandle;
  replay: boolean;
  debug: boolean;
  onDebug: (b: boolean) => void;
}) {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [minSeverity, setMinSeverity] = useState<MinSeverity>("all");
  const [search, setSearch] = useState("");
  const [paused, setPaused] = useState(false);
  const [frozen, setFrozen] = useState<FeedState | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const leftAt = useRef<number>(0);
  const list = useRef<VirtualHandle>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const shown: FeedState = paused && frozen ? frozen : handle.feed;
  const filters: FeedFilters = useMemo(() => ({ hidden, minSeverity, search }), [hidden, minSeverity, search]);
  const rows = useMemo(() => buildRows(shown.events, filters), [shown.events, filters]);
  const counts = useMemo(() => countBySource(shown.events), [shown.events]);
  const sources = useMemo(() => {
    const known = SOURCE_ORDER.filter((s) => counts[s] || !replay);
    const extra = Object.keys(counts).filter((s) => !SOURCE_ORDER.includes(s)).sort();
    return [...known, ...extra];
  }, [counts, replay]);

  const follow = !replay ? atBottom && !paused : false;
  const newCount = Math.max(0, handle.feed.accepted - (paused && frozen ? frozen.accepted : leftAt.current));
  const showPill = !replay ? !follow && newCount > 0 : false;

  const onAtBottom = useCallback(
    (b: boolean) => {
      setAtBottom(b);
      if (!b) leftAt.current = handle.feed.accepted;
    },
    [handle.feed.accepted],
  );

  const togglePause = () => {
    if (paused) {
      setPaused(false);
      setFrozen(null);
      setAtBottom(true);
      requestAnimationFrame(() => list.current?.scrollToBottom());
    } else {
      setFrozen(handle.feed);
      setPaused(true);
    }
  };
  const jumpToNow = () => {
    setPaused(false);
    setFrozen(null);
    setAtBottom(true);
    requestAnimationFrame(() => list.current?.scrollToBottom());
  };
  const toggle = useCallback((key: string) => {
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  }, []);
  const toggleSource = (s: string) =>
    setHidden((h) => {
      const n = new Set(h);
      if (n.has(s)) n.delete(s);
      else n.add(s);
      return n;
    });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key === "/" && t && !/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) && !t.isContentEditable) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const keyOf = useCallback((r: FeedRow) => r.key, []);
  const render = useCallback(
    (r: FeedRow) => <FeedCard runId={runId} row={r} expanded={expanded.has(r.key)} onToggle={toggle} query={search} />,
    [runId, expanded, toggle, search],
  );
  const filtered = hidden.size > 0 || minSeverity !== "all" || search.trim() !== "";
  const empty = rows.length === 0;

  return (
    <section className="feed" aria-label={replay ? "Replay feed" : "Live feed"}>
      <header className="feed-bar">
        <div className="feed-bar-row">
          <h2 className="feed-title">{replay ? "Replay" : "Feed"}</h2>
          {statusBadge(handle, replay)}
          <span className="muted feed-count" aria-live="polite">
            {filtered ? `${rows.length} shown of ${shown.events.length}` : `${rows.length} events`}
            {shown.dropped > 0 && ` · ${shown.dropped} older not kept`}
          </span>
          <span className="feed-spacer" />
          <label className="feed-search">
            <Icon name="search" size={14} />
            <span className="visually-hidden">Search the feed</span>
            <input ref={searchRef} type="search" className="field" placeholder="Search (press /)" value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          <label className="feed-sev">
            <span className="visually-hidden">Minimum severity</span>
            <select className="field" value={minSeverity} onChange={(e) => setMinSeverity(e.target.value as MinSeverity)} aria-label="Minimum severity">
              <option value="all">All levels</option>
              <option value="warning">Warnings and above</option>
              <option value="violation">Violations and kills</option>
            </select>
          </label>
          <label className="feed-debug" title="Also show raw CLI echoes, per-request telemetry and scorer internals">
            <input type="checkbox" checked={debug} onChange={(e) => onDebug(e.target.checked)} /> Debug rows
          </label>
          {!replay && (
            <button type="button" className={`btn btn-small${paused ? " btn-on" : ""}`} onClick={togglePause} aria-pressed={paused}>
              <Icon name="pause" size={14} /> {paused ? "Resume" : "Pause"}
            </button>
          )}
        </div>
        <div className="feed-chips" role="group" aria-label="Sources">
          {sources.map((s) => {
            const off = hidden.has(s);
            return (
              <button key={s} type="button" className={`chip${off ? " chip-off" : ""}`} aria-pressed={!off} onClick={() => toggleSource(s)}>
                {SOURCE_LABEL[s] ?? s}
                <span className="chip-n">{counts[s] ?? 0}</span>
              </button>
            );
          })}
        </div>
      </header>
      <div className="feed-body">
        {empty ? (
          <div className="feed-empty">
            {handle.status === "replay-error" ? (
              <>
                <strong>Could not load the log.</strong>
                <span className="muted">{handle.error}</span>
                <button type="button" className="btn" onClick={handle.restart}>Try again</button>
              </>
            ) : handle.status === "connecting" || handle.status === "replay-loading" || (!handle.caughtUp && !replay) ? (
              <span className="muted">Loading events…</span>
            ) : filtered ? (
              <span className="muted">No events match the filters.</span>
            ) : (
              <span className="muted">{replay ? "This run logged no visible events." : "Waiting for the first event…"}</span>
            )}
          </div>
        ) : (
          <VirtualList
            items={rows}
            keyOf={keyOf}
            render={render}
            follow={follow}
            onAtBottomChange={onAtBottom}
            handleRef={list}
            label={replay ? "Replay events" : "Live events"}
            onNearEnd={replay ? handle.loadMore : undefined}
          />
        )}
        {showPill && (
          <button type="button" className="feed-pill" onClick={jumpToNow}>
            <Icon name="down" size={14} /> {newCount} new event{newCount === 1 ? "" : "s"}
          </button>
        )}
        {!replay && !showPill && !follow && !empty && (
          <button type="button" className="feed-pill feed-pill-quiet" onClick={jumpToNow}>
            <Icon name="down" size={14} /> Jump to now
          </button>
        )}
      </div>
      <footer className="feed-foot muted">
        {replay ? (
          handle.loadingMore ? (
            "Loading more…"
          ) : handle.atEnd ? (
            "End of the log."
          ) : (
            <button type="button" className="btn btn-small" onClick={handle.loadMore}>Load more</button>
          )
        ) : handle.ended ? (
          `Run ended${handle.ended.state ? ` (${handle.ended.state.toLowerCase().replace(/_/g, " ")})` : ""}${handle.ended.crashed ? ", harness stopped without an end record" : ""}.`
        ) : handle.ending ? (
          "Run finished; the last checkpoints are still being scored."
        ) : (
          "Observing only. Nothing here can affect the agent."
        )}
        {replay && handle.feed.dropped > 0 && (
          <button type="button" className="btn btn-small" onClick={handle.restart}>Back to the start</button>
        )}
      </footer>
    </section>
  );
}
