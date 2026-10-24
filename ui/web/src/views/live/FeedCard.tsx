import { memo, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../../components";
import { asRec, cardModel, detailJson, fmtOffset } from "./cardModel";
import type { FeedRow } from "./feedStore";
import { Icon } from "./icons";
import { liveApi, transcriptLink } from "./liveApi";
import type { DisplayEvent } from "./types";

/** Text with every case-insensitive match of `q` wrapped in <mark>. Pure React text nodes, never HTML. */
export function Highlight({ text, q }: { text: string; q: string }): ReactNode {
  const needle = q.trim().toLowerCase();
  if (!needle) return text;
  const hay = text.toLowerCase();
  const parts: ReactNode[] = [];
  let i = 0;
  let n = 0;
  while (i < text.length && n < 20) {
    const j = hay.indexOf(needle, i);
    if (j < 0) break;
    if (j > i) parts.push(text.slice(i, j));
    parts.push(<mark key={j}>{text.slice(j, j + needle.length)}</mark>);
    i = j + needle.length;
    n++;
  }
  if (parts.length === 0) return text;
  if (i < text.length) parts.push(text.slice(i));
  return parts;
}

/** Fetch the full (larger-cap) version of an event the first time its card is expanded. */
function useFullEvent(runId: string, ev: DisplayEvent, want: boolean) {
  const [full, setFull] = useState<DisplayEvent | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!want) return;
    const ctl = new AbortController();
    setLoading(true);
    liveApi
      .feedEvent(runId, ev.cursor, ctl.signal)
      .then((f) => {
        if (!ctl.signal.aborted) setFull(f);
      })
      .catch((e: unknown) => {
        if (!ctl.signal.aborted) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
    return () => ctl.abort();
  }, [want, runId, ev.cursor]);
  return { full, err, loading };
}

function Detail({ runId, row }: { runId: string; row: FeedRow }) {
  const { ev, result } = row;
  const needFull = !!(ev.truncated || result?.truncated) && ev.kind !== "folded";
  const f = useFullEvent(runId, ev, needFull);
  const shown = f.full ?? ev;
  const payload: unknown = result ? { call: shown.payload_preview, result: result.payload_preview } : shown.payload_preview;
  const j = detailJson(ev.kind === "folded" ? { fold: ev.fold, ...asRec(ev.payload_preview) } : payload);
  const [copied, setCopied] = useState(false);
  const p = asRec(shown.payload_preview);
  const body = typeof p.text === "string" ? p.text : typeof p.message === "string" ? p.message : null;

  const copy = () => {
    try {
      void navigator.clipboard?.writeText(JSON.stringify(result ? { call: shown, result } : shown, null, 2)).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      });
    } catch {
      /* clipboard unavailable: nothing to do */
    }
  };

  return (
    <div className="fc-detail">
      <dl className="fc-meta">
        <div><dt>source</dt><dd>{ev.source}</dd></div>
        <div><dt>type</dt><dd>{ev.type}</dd></div>
        <div><dt>ref</dt><dd className="mono">{ev.cursor}</dd></div>
        {ev.ts && <div><dt>time</dt><dd className="mono">{ev.ts}</dd></div>}
        {shown.raw_bytes != null && <div><dt>raw</dt><dd>{shown.raw_bytes} B</dd></div>}
      </dl>
      {body && <div className="fc-fulltext" data-testid="fulltext">{body}</div>}
      {result && <div className="fc-result"><span className="muted">result</span> {result.title}{result.summary ? ` – ${result.summary}` : ""}</div>}
      {f.loading && <div className="muted fc-note">Loading the full event…</div>}
      {f.err && <div className="fc-note fc-note-bad" role="alert">Could not load the full event: {f.err}</div>}
      <pre className="fc-json" tabIndex={0} aria-label="Event payload (text)">{j.text}</pre>
      {j.cut > 0 && <div className="muted fc-note">{j.cut} more characters not shown.</div>}
      <div className="fc-actions-row">
        <button type="button" className="btn btn-small" onClick={copy}>
          <Icon name="copy" size={14} /> {copied ? "Copied" : "Copy JSON"}
        </button>
        <Link className="btn btn-small" to={transcriptLink(runId, ev.cursor)}>
          <Icon name="link" size={14} /> Open in transcript
        </Link>
      </div>
    </div>
  );
}

export const FeedCard = memo(function FeedCard({
  runId,
  row,
  expanded,
  onToggle,
  query,
}: {
  runId: string;
  row: FeedRow;
  expanded: boolean;
  onToggle: (key: string) => void;
  query: string;
}) {
  const { ev, result } = row;
  const m = cardModel(ev, result);
  const sev = result && result.severity === "warning" && ev.severity === "info" ? "warning" : ev.severity;
  const mono = ev.kind === "tool_call" || ev.kind === "guardrail";
  const detailId = `fc-d-${row.key.replace(/[^A-Za-z0-9_-]/g, "_")}`;
  return (
    <article
      className={`fc fc-sev-${sev} k-${m.accent}${m.quiet ? " fc-quiet" : ""}${expanded ? " fc-open" : ""}`}
      data-kind={ev.kind}
      data-testid={`card-${ev.kind}`}
    >
      <div className="fc-row">
        <span className="fc-icon" aria-hidden="true"><Icon name={m.icon} size={15} /></span>
        <button type="button" className="fc-toggle" aria-expanded={expanded} aria-controls={expanded ? detailId : undefined} onClick={() => onToggle(row.key)}>
          <span className="fc-time mono" title={ev.ts ?? undefined}>{fmtOffset(ev.t_s)}</span>
          <span className="fc-main">
            <span className="fc-line">
              <span className="fc-title"><Highlight text={ev.title} q={query} /></span>
              {sev !== "info" && <span className="visually-hidden"> ({sev})</span>}
              {ev.summary && !m.text && (
                <span className={`fc-summary${mono ? " mono" : ""}`}> <Highlight text={ev.summary} q={query} /></span>
              )}
            </span>
            {m.text && <span className="fc-text"><Highlight text={m.text} q={query} /></span>}
          </span>
          <span className="fc-chips">
            {m.chips.map((c, i) => (
              <Badge key={i} tone={c.tone ?? "neutral"} plain title={c.title}>{c.text}</Badge>
            ))}
          </span>
          <span className="fc-chev" aria-hidden="true"><Icon name="chevron" size={14} /></span>
        </button>
      </div>
      {expanded && (
        <div id={detailId}>
          <Detail runId={runId} row={row} />
        </div>
      )}
    </article>
  );
});
