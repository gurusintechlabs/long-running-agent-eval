import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, EmptyState, ErrorState, Spinner } from "../../../components";
import { Chip, Notice } from "../common/Widgets";
import { TranscriptRow } from "./TranscriptItems";
import { useTranscript, type Target } from "./useTranscript";

const KINDS: [string, string][] = [
  ["text", "Assistant text"],
  ["tool", "Tool calls"],
  ["test_run", "Test runs"],
  ["compaction", "Compactions"],
];

function targetFrom(params: URLSearchParams): Target {
  const cursor = params.get("cursor");
  const t = params.get("t_s");
  const t_s = t != null && t !== "" && Number.isFinite(Number(t)) ? Number(t) : null;
  return { cursor: cursor || null, t_s: cursor ? null : t_s };
}

export function TranscriptTab({ runId }: { runId: string; live?: boolean }) {
  const [params, setParams] = useSearchParams();
  const target = targetFrom(params);
  const [tools, setTools] = useState<string[]>([]);
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [kind, setKind] = useState<string[]>([]);
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setQ(qInput.trim()), 300);
    return () => clearTimeout(id);
  }, [qInput]);

  const tr = useTranscript(runId, { tools, errorsOnly, q, kind }, target);
  const list = useRef<HTMLOListElement>(null);

  // Scroll the targeted item into view once the window has loaded.
  useEffect(() => {
    if (!tr.anchor || tr.loading) return;
    const el = Array.from(list.current?.querySelectorAll<HTMLElement>("[data-cursor]") ?? []).find((n) => n.dataset.cursor === tr.anchor);
    if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "center" });
  }, [tr.anchor, tr.loading]);

  const clearTarget = () => {
    const p = new URLSearchParams(params);
    p.delete("cursor");
    p.delete("t_s");
    setParams(p);
  };
  const toggle = <T,>(arr: T[], v: T, set: (a: T[]) => void) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const filtered = tools.length > 0 || errorsOnly || kind.length > 0 || q !== "";

  return (
    <Card
      title={`Transcript${tr.total ? ` (${tr.total.toLocaleString("en-US")} items)` : ""}`}
      actions={
        <button type="button" className="btn" onClick={tr.reload}>
          Refresh
        </button>
      }
    >
      <div className="tr-filters">
        <input className="field tr-search" type="search" placeholder="Search text, tool name, input and result" aria-label="Search transcript" value={qInput} onChange={(e) => setQInput(e.target.value)} />
        <Chip on={errorsOnly} onClick={() => setErrorsOnly(!errorsOnly)}>Errors only</Chip>
        {KINDS.map(([k, l]) => (
          <Chip key={k} on={kind.includes(k)} onClick={() => toggle(kind, k, setKind)}>
            {l}
          </Chip>
        ))}
      </div>
      {tr.tools.length > 0 && (
        <div className="picker" role="group" aria-label="Filter by tool">
          {tr.tools.slice(0, 16).map((t) => (
            <Chip key={t.tool ?? "?"} on={tools.includes(t.tool ?? "")} onClick={() => toggle(tools, t.tool ?? "", setTools)} title={`${t.count} calls, ${t.errors} errors`}>
              {t.tool ?? "(unknown)"} <span className="muted">{t.count}</span>
              {t.errors > 0 && <span className="tr-errn"> {t.errors}!</span>}
            </Chip>
          ))}
        </div>
      )}

      {tr.hasTarget && (
        <Notice tone="info">
          <span>
            Showing a window around {target.cursor ? <>the log position <span className="mono">{target.cursor}</span></> : <>run time {target.t_s}s</>}
            {filtered ? " (filters apply inside the window)" : ""}.
          </span>{" "}
          <button type="button" className="link-btn" onClick={clearTarget}>Back to the start of the transcript</button>
        </Notice>
      )}

      {tr.error && tr.items.length === 0 ? (
        <ErrorState title="Could not load the transcript" error={tr.error} onRetry={tr.reload} />
      ) : tr.loading ? (
        <Spinner label="Loading transcript" />
      ) : tr.items.length === 0 ? (
        <EmptyState title={filtered ? "No items match these filters" : "Nothing in the transcript yet"}>
          {filtered ? "Clear a filter to see more." : "Items appear as the agent works."}
        </EmptyState>
      ) : (
        <>
          {tr.mode === "around" && (
            <div className="tr-more">
              <button type="button" className="btn" onClick={tr.loadEarlier} disabled={tr.more}>Show 40 earlier items</button>
            </div>
          )}
          <ol className="tr-list" ref={list}>
            {tr.items.map((it) => (
              <TranscriptRow key={it.cursor} runId={runId} it={it} highlighted={it.cursor === tr.anchor} />
            ))}
          </ol>
          {tr.error && <Notice tone="bad">{tr.error.message}</Notice>}
          <div className="tr-more">
            {!tr.eof ? (
              <button type="button" className="btn" onClick={() => tr.loadMore()} disabled={tr.more}>
                {tr.more ? "Loading…" : tr.mode === "around" ? "Load later items" : "Load more"}
              </button>
            ) : (
              <>
                <span className="muted">End of the transcript{filtered ? " (filtered)" : ""}.</span>
                <button type="button" className="link-btn" onClick={() => tr.loadMore(true)} disabled={tr.more}>Check for new items</button>
              </>
            )}
          </div>
        </>
      )}
    </Card>
  );
}
