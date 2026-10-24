import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { timelineApi, useAsync, type CheckpointRow, type DiffResponse } from "../../../api";
import { Badge, ErrorState, Spinner } from "../../../components";
import { EMPTY, formatDuration, shortSha } from "../../../lib/format";
import { formatBytes } from "../../../lib/text";
import { CopyButton, ExpandableText, Notice } from "../common/Widgets";
import { DiffViewer } from "./DiffViewer";

type Pane = "diff" | "commits" | "scorer";
const PANES: [Pane, string][] = [
  ["diff", "Diff"],
  ["commits", "Commits"],
  ["scorer", "Scorer log"],
];

export function CheckpointDrawer({ runId, k, row, onClose }: { runId: string; k: number; row: CheckpointRow | null; onClose: () => void }) {
  const [pane, setPane] = useState<Pane>("diff");
  const dialog = useRef<HTMLDivElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    opener.current = document.activeElement;
    closeBtn.current?.focus();
    return () => {
      if (opener.current instanceof HTMLElement) opener.current.focus();
    };
  }, []);

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !dialog.current) return;
    const f = dialog.current.querySelectorAll<HTMLElement>("button, a[href], input, select, [tabindex]:not([tabindex='-1'])");
    if (f.length === 0) return;
    const first = f[0];
    const last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const diffQ = useAsync((s) => timelineApi.diff(runId, k, {}, s), [runId, k]);
  const scorerQ = useAsync((s) => (pane === "scorer" ? timelineApi.scorerLog(runId, k, s) : Promise.resolve(null)), [runId, k, pane === "scorer"]);

  return (
    <div className="drawer-wrap" onKeyDown={onKey}>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" ref={dialog}>
        <header className="drawer-head">
          <div>
            <h2 id="drawer-title">Checkpoint t{k}</h2>
            <div className="muted drawer-sub">
              {row ? (
                <>
                  {formatDuration(row.t_s)} · head <span className="mono">{shortSha(row.head_sha)}</span>{" "}
                  {row.dirty ? <Badge tone="warn" plain>uncommitted files</Badge> : row.dirty === false ? <Badge tone="ok" plain>clean</Badge> : null}
                </>
              ) : (
                EMPTY
              )}
            </div>
          </div>
          <button type="button" className="btn" ref={closeBtn} onClick={onClose}>
            Close
          </button>
        </header>
        <div className="tabs tabs-sub" role="tablist" aria-label="Checkpoint details">
          {PANES.map(([id, label]) => (
            <button key={id} type="button" role="tab" id={`cp-tab-${id}`} aria-selected={pane === id} aria-controls="cp-pane" tabIndex={pane === id ? 0 : -1} className={`tab${pane === id ? " tab-on" : ""}`} onClick={() => setPane(id)}>
              {label}
              {id === "commits" && diffQ.data ? ` (${diffQ.data.commits.length})` : ""}
            </button>
          ))}
        </div>
        <div className="drawer-body" id="cp-pane" role="tabpanel" aria-labelledby={`cp-tab-${pane}`}>
          {pane !== "scorer" &&
            (diffQ.error && !diffQ.data ? (
              <ErrorState title="Could not load the git view" error={diffQ.error} onRetry={diffQ.reload} />
            ) : !diffQ.data ? (
              <Spinner label="Loading diff" />
            ) : pane === "diff" ? (
              <DiffViewer d={diffQ.data} />
            ) : (
              <Commits d={diffQ.data} />
            ))}
          {pane === "scorer" &&
            (scorerQ.error && !scorerQ.data ? (
              <ErrorState title="No scorer log for this checkpoint" error={scorerQ.error} onRetry={scorerQ.reload} />
            ) : !scorerQ.data ? (
              <Spinner label="Loading scorer log" />
            ) : (
              <div>
                <p className="muted">
                  scorer/score-t{k}.log · {formatBytes(scorerQ.data.size)}
                </p>
                {scorerQ.data.truncated && <Notice tone="warn">Only the end of the log is shown.</Notice>}
                <ExpandableText text={scorerQ.data.text || "(empty)"} max={6000} className="log" defaultOpen={scorerQ.data.text.length <= 12000} />
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}

function Commits({ d }: { d: DiffResponse }) {
  if (!d.available) return <Notice tone="warn">No git view for this checkpoint: {d.reason ?? "unavailable"}.</Notice>;
  if (d.commits.length === 0) return <p className="muted">No commits between the previous checkpoint and this one.</p>;
  return (
    <>
      <ul className="commits">
        {d.commits.map((c) => (
          <li key={c.sha} className="commit">
            <div className="commit-subj">{c.subject || "(no subject)"}</div>
            <div className="muted commit-meta">
              <span className="mono">{c.sha.slice(0, 10)}</span>
              <span>{c.author ?? "?"}</span>
              <span>{c.date ?? ""}</span>
              <CopyButton text={c.sha} label="Copy sha" />
            </div>
          </li>
        ))}
      </ul>
      {d.commits_truncated && <Notice tone="warn">The commit list was cut at the server limit.</Notice>}
    </>
  );
}
