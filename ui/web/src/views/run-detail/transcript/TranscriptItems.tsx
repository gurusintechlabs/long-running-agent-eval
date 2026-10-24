import { useState } from "react";
import { transcriptApi, type TextItem, type ToolItem, type TranscriptItem, type TranscriptItemDetail } from "../../../api";
import { Badge } from "../../../components";
import { clip, formatBytes, formatClock } from "../../../lib/text";
import { CopyButton, ExpandableText, Notice } from "../common/Widgets";

function payloadOf(ev: TranscriptItemDetail["event"]): Record<string, unknown> {
  const p = ev?.payload;
  return p && typeof p === "object" ? (p as Record<string, unknown>) : {};
}

function when(it: TranscriptItem) {
  return (
    <span className="tr-time mono" title={it.ts ?? undefined}>
      {formatClock(it.t_s)}
    </span>
  );
}

function useDetail(runId: string, cursor: string) {
  const [d, setD] = useState<{ loading: boolean; data: TranscriptItemDetail | null; error: Error | null }>({ loading: false, data: null, error: null });
  const load = () => {
    if (d.loading || d.data) return;
    setD({ loading: true, data: null, error: null });
    transcriptApi
      .item(runId, cursor)
      .then((data) => setD({ loading: false, data, error: null }))
      .catch((e: unknown) => setD({ loading: false, data: null, error: e instanceof Error ? e : new Error(String(e)) }));
  };
  return { ...d, load };
}

function prettyInput(input: unknown): string {
  if (typeof input === "string") return input;
  try {
    return JSON.stringify(input, null, 2) ?? "";
  } catch {
    return String(input);
  }
}

function TextView({ runId, it }: { runId: string; it: TextItem }) {
  const full = useDetail(runId, it.cursor);
  const fullText = full.data ? payloadOf(full.data.event).text : null;
  const text = typeof fullText === "string" ? fullText : it.text;
  return (
    <div className="tr-body">
      <ExpandableText text={text} max={700} className="tr-text" />
      {it.text_truncated && typeof fullText !== "string" && (
        <button type="button" className="link-btn" onClick={full.load} disabled={full.loading}>
          {full.loading ? "Loading…" : `Load full text (${it.chars.toLocaleString("en-US")} chars)`}
        </button>
      )}
      {full.error && <Notice tone="bad">{full.error.message}</Notice>}
    </div>
  );
}

function ToolView({ runId, it }: { runId: string; it: ToolItem }) {
  const [open, setOpen] = useState(false);
  const detail = useDetail(runId, it.cursor);
  const toggle = () => {
    if (!open) detail.load();
    setOpen(!open);
  };
  const ev = payloadOf(detail.data?.event ?? null);
  const input = prettyInput(ev.input);
  const resultText = detail.data?.result_text ?? it.result_tail ?? "";
  const tone = it.status === "error" ? "bad" : it.status === "pending" ? "warn" : "ok";
  const bodyId = `tool-${it.cursor.replace(/\W/g, "_")}`;
  return (
    <div className="tr-body">
      <button type="button" className="tool-head" aria-expanded={open} aria-controls={bodyId} onClick={toggle}>
        <span className="tool-caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
        <span className="tool-name mono">{it.tool ?? "(unknown tool)"}</span>
        <span className="tool-sum mono">{clip(it.input_summary, 160)}</span>
        <Badge tone={tone} plain>{it.status}</Badge>
        {it.dur_s != null && <span className="muted tool-meta">{it.dur_s.toFixed(it.dur_s < 10 ? 2 : 0)} s</span>}
        {it.result_size != null && <span className="muted tool-meta">{formatBytes(it.result_size)}</span>}
      </button>
      {!open && it.result_tail && it.status === "error" && <pre className="tool-tail">{clip(it.result_tail, 300)}</pre>}
      {open && (
        <div id={bodyId} className="tool-detail">
          {detail.loading && <p className="muted">Loading full input and result…</p>}
          {detail.error && <Notice tone="bad">{detail.error.message}</Notice>}
          {detail.data && (
            <>
              <h4>Input{it.input_truncated ? " (truncated in the log)" : ""}</h4>
              <ExpandableText text={input || "(empty)"} max={1200} />
              <h4>Result</h4>
              {detail.data.result_text == null && !it.has_result ? (
                <p className="muted">No result recorded yet.</p>
              ) : (
                <ExpandableText
                  text={resultText || "(empty)"}
                  max={1500}
                  note={detail.data.result_text_truncated ? <span className="muted">result cut at 200,000 characters</span> : undefined}
                />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

const KIND_LABEL: Record<string, string> = { text: "Assistant", tool: "Tool", compaction: "Compaction", test_run: "Tests", session: "Session", denied: "Denied" };

export function TranscriptRow({ runId, it, highlighted }: { runId: string; it: TranscriptItem; highlighted: boolean }) {
  let body;
  switch (it.kind) {
    case "text":
      body = <TextView runId={runId} it={it} />;
      break;
    case "tool":
      body = <ToolView runId={runId} it={it} />;
      break;
    case "compaction":
      body = (
        <div className="tr-body tr-line">
          Context compaction ({it.trigger ?? "?"}){it.pre_tokens != null ? `, ${it.pre_tokens.toLocaleString("en-US")} tokens before` : ""}
        </div>
      );
      break;
    case "test_run":
      body = (
        <div className="tr-body tr-line">
          Test run: <span className="mono">{it.raw_summary ?? `${it.passed ?? 0} passed, ${it.failed ?? 0} failed`}</span>
        </div>
      );
      break;
    case "session":
      body = (
        <div className="tr-body tr-line">
          {it.event}
          {it.model ? ` · ${it.model}` : ""}
          {it.subtype ? ` · ${it.subtype}` : ""}
          {it.num_turns != null ? ` · ${it.num_turns} turns` : ""}
          {it.total_cost_usd != null ? ` · est. $${it.total_cost_usd.toFixed(2)}` : ""}
        </div>
      );
      break;
    case "denied":
      body = (
        <div className="tr-body tr-line">
          Permission denied: <span className="mono">{it.tool}</span> {clip(it.input_summary, 160)}
        </div>
      );
      break;
  }
  const tone = it.kind === "tool" && it.status === "error" ? "bad" : it.kind === "denied" ? "bad" : it.kind === "text" ? "info" : "neutral";
  return (
    <li className={`tr-item tr-${it.kind}${highlighted ? " tr-hl" : ""}`} data-cursor={it.cursor} aria-current={highlighted ? "true" : undefined}>
      <div className="tr-meta">
        {when(it)}
        <Badge tone={tone} plain>{KIND_LABEL[it.kind]}</Badge>
        {it.turn != null && <span className="muted">turn {it.turn}</span>}
        {highlighted && <Badge tone="warn" plain>target</Badge>}
        <span className="tr-spacer" />
        <CopyButton text={it.cursor} label="Copy cursor" />
      </div>
      {body}
    </li>
  );
}
