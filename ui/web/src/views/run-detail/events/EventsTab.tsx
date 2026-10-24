import { useEffect, useMemo, useRef, useState } from "react";
import { EVENT_SOURCES, eventsApi, useAsync, type EventsResponse, type LogEvent } from "../../../api";
import { Badge, Card, EmptyState, ErrorState, Spinner } from "../../../components";
import { clip, formatBytes, formatClock } from "../../../lib/text";
import { Chip, CopyButton, Notice } from "../common/Widgets";
import { JsonView } from "./JsonView";

const PAGE = 200;

const SOURCE_TONE: Record<string, "info" | "ok" | "warn" | "bad" | "neutral"> = {
  agent_stream: "info",
  otel: "neutral",
  orchestrator: "ok",
  guardrail: "bad",
  counterpart: "warn",
  env: "warn",
  scorer: "ok",
};

function preview(p: unknown): string {
  try {
    return clip(typeof p === "string" ? p : JSON.stringify(p), 200);
  } catch {
    return "";
  }
}

function isCut(e: LogEvent): boolean {
  const p = e.payload;
  return e.truncated || (p != null && typeof p === "object" && (p as { _truncated?: unknown })._truncated === true);
}

export function EventsTab({ runId }: { runId: string; live?: boolean }) {
  const [sources, setSources] = useState<string[]>([]);
  const [type, setType] = useState("");
  const [qIn, setQIn] = useState("");
  const [q, setQ] = useState("");
  const [typeApplied, setTypeApplied] = useState("");
  useEffect(() => {
    const id = setTimeout(() => {
      setQ(qIn.trim());
      setTypeApplied(type.trim());
    }, 350);
    return () => clearTimeout(id);
  }, [qIn, type]);

  const summary = useAsync((s) => eventsApi.summary(runId, s), [runId]);
  const types = useMemo(() => {
    const set = new Set<string>();
    for (const [src, v] of Object.entries(summary.data?.sources ?? {})) if (sources.length === 0 || sources.includes(src)) for (const t of Object.keys(v.counts)) set.add(t);
    return [...set].sort();
  }, [summary.data, sources]);

  const [events, setEvents] = useState<LogEvent[]>([]);
  const [meta, setMeta] = useState<Pick<EventsResponse, "next" | "eof" | "scan_capped" | "page_capped" | "mode"> | null>(null);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);
  const ctl = useRef<AbortController | null>(null);
  const filterKey = JSON.stringify([runId, sources, typeApplied, q, tick]);

  const params = () => ({ source: sources.length ? sources : undefined, type: typeApplied || undefined, q: q || undefined, limit: PAGE });

  useEffect(() => {
    ctl.current?.abort();
    const c = new AbortController();
    ctl.current = c;
    setLoading(true);
    setError(null);
    setEvents([]);
    eventsApi
      .list(runId, params(), c.signal)
      .then((r) => {
        if (c.signal.aborted) return;
        setEvents(r.events);
        setMeta(r);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (c.signal.aborted) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        setLoading(false);
      });
    return () => c.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  const loadMore = () => {
    if (!meta || more) return;
    setMore(true);
    eventsApi
      .list(runId, { ...params(), after: meta.next })
      .then((r) => {
        setEvents((p) => [...p, ...r.events]);
        setMeta(r);
        setMore(false);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e : new Error(String(e)));
        setMore(false);
      });
  };

  const toggleSource = (s: string) => setSources((p) => (p.includes(s) ? p.filter((x) => x !== s) : [...p, s]));
  const available = EVENT_SOURCES.filter((s) => !summary.data || summary.data.sources[s]);

  return (
    <Card
      title="Events"
      actions={
        <button type="button" className="btn" onClick={() => setTick((t) => t + 1)}>
          Refresh
        </button>
      }
    >
      <div className="tr-filters">
        <input className="field tr-search" type="search" placeholder="Search the raw JSON of every event" aria-label="Search events" value={qIn} onChange={(e) => setQIn(e.target.value)} />
        <input
          className="field"
          type="text"
          list="event-types"
          placeholder="type, e.g. tool.call or stream.*"
          aria-label="Filter by event type"
          value={type}
          onChange={(e) => setType(e.target.value)}
          style={{ minWidth: 230 }}
        />
        <datalist id="event-types">
          {types.slice(0, 300).map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
      </div>
      <div className="picker" role="group" aria-label="Filter by source">
        {available.map((s) => (
          <Chip key={s} on={sources.includes(s)} onClick={() => toggleSource(s)} title={summary.data?.sources[s] ? `${summary.data.sources[s].lines.toLocaleString("en-US")} lines` : undefined}>
            {s}
            {summary.data?.sources[s] && <span className="muted"> {summary.data.sources[s].lines.toLocaleString("en-US")}</span>}
          </Chip>
        ))}
        <span className="muted ev-hint">{sources.length === 0 ? "all sources, merged by time" : `${sources.length} selected`}</span>
      </div>

      {error && events.length === 0 ? (
        <ErrorState title="Could not load events" error={error} onRetry={() => setTick((t) => t + 1)} />
      ) : loading ? (
        <Spinner label="Loading events" />
      ) : events.length === 0 ? (
        <EmptyState title="No events match">
          {meta && !meta.eof ? "The search window was capped before a match; use Continue searching." : "Change the filters or clear the search."}
          {meta && !meta.eof && (
            <button type="button" className="btn" onClick={loadMore} disabled={more}>
              Continue searching
            </button>
          )}
        </EmptyState>
      ) : (
        <>
          <ol className="ev-list">
            {events.map((e) => (
              <EventRow key={`${e.cursor}-${e.source}`} runId={runId} e={e} />
            ))}
          </ol>
          {error && <Notice tone="bad">{error.message}</Notice>}
          {meta?.mode === "merged" && <p className="muted chart-note">Merged by timestamp; otel rows can be up to about 1 s out of order.</p>}
          <div className="tr-more">
            {meta && !meta.eof ? (
              <button type="button" className="btn" onClick={loadMore} disabled={more}>
                {more ? "Loading…" : meta.scan_capped ? "Continue searching" : "Load more"}
              </button>
            ) : (
              <span className="muted">End of the log ({events.length.toLocaleString("en-US")} shown).</span>
            )}
          </div>
        </>
      )}
    </Card>
  );
}

function EventRow({ runId, e }: { runId: string; e: LogEvent }) {
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState<LogEvent | null>(null);
  const [loadingFull, setLoadingFull] = useState(false);
  const [err, setErr] = useState<Error | null>(null);
  const shown = full ?? e;
  const cut = !full && isCut(e);
  const loadFull = () => {
    setLoadingFull(true);
    eventsApi
      .at(runId, e.cursor)
      .then((r) => setFull(r.event))
      .catch((x: unknown) => setErr(x instanceof Error ? x : new Error(String(x))))
      .finally(() => setLoadingFull(false));
  };
  const json = () => JSON.stringify(shown, null, 2);
  const id = `ev-${e.source}-${e.cursor.replace(/\W/g, "_")}`;
  return (
    <li className={`ev${open ? " ev-open" : ""}`}>
      <button type="button" className="ev-head" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <span className="mono ev-time">{formatClock(e.t_s)}</span>
        <Badge tone={SOURCE_TONE[e.source] ?? "neutral"} plain>{e.source}</Badge>
        <span className="mono ev-type">{e.type}</span>
        {!open && <span className="ev-prev mono">{preview(e.payload)}</span>}
      </button>
      {open && (
        <div id={id} className="ev-body">
          <div className="ev-meta muted">
            <span>cursor <span className="mono">{e.cursor}</span></span>
            <span>seq {e.seq ?? "–"}</span>
            <span>{formatBytes(e.bytes)}</span>
            {e.ts && <span className="mono">{e.ts}</span>}
            <CopyButton text={json} label="Copy JSON" />
          </div>
          {cut && (
            <Notice tone="warn">
              Shown cut to keep the page light.{" "}
              <button type="button" className="link-btn" onClick={loadFull} disabled={loadingFull}>
                {loadingFull ? "Loading…" : "Load the full event"}
              </button>
            </Notice>
          )}
          {err && <Notice tone="bad">{err.message}</Notice>}
          <JsonView value={shown.payload} />
        </div>
      )}
    </li>
  );
}
