import { useMemo, useState } from "react";
import type { DiffResponse } from "../../../api";
import { Badge } from "../../../components";
import { formatBytes } from "../../../lib/text";
import { CopyButton, Notice } from "../common/Widgets";
import { parseDiff, type DiffFile } from "./diffParse";

const LINE_CAP = 1500;
const AUTO_OPEN_LINES = 600;

function FileSection({ f, defaultOpen }: { f: DiffFile; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const [cap, setCap] = useState(LINE_CAP);
  const id = `df-${f.path.replace(/\W/g, "_")}`;
  return (
    <section className="df">
      <button type="button" className="df-head" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        <span className="mono df-path">{f.path}</span>
        {f.binary ? <Badge tone="neutral" plain>binary</Badge> : (
          <span className="df-stat mono">
            <span className="df-plus">+{f.added}</span> <span className="df-minus">-{f.deleted}</span>
          </span>
        )}
      </button>
      {open && (
        <div id={id} className="df-body" role="table" aria-label={`Diff of ${f.path}`}>
          {f.lines.slice(0, cap).map((l, i) => (
            <div key={i} className={`dl dl-${l.kind}`} role="row">
              <span className="dl-no" role="cell" aria-label={l.oldNo != null ? `old line ${l.oldNo}` : undefined}>{l.oldNo ?? ""}</span>
              <span className="dl-no" role="cell" aria-label={l.newNo != null ? `new line ${l.newNo}` : undefined}>{l.newNo ?? ""}</span>
              <span className="dl-sign" role="cell" aria-hidden="true">{l.kind === "add" ? "+" : l.kind === "del" ? "-" : ""}</span>
              <span className="dl-text" role="cell">
                {l.kind === "add" && <span className="visually-hidden">added: </span>}
                {l.kind === "del" && <span className="visually-hidden">removed: </span>}
                {l.text}
              </span>
            </div>
          ))}
          {f.lines.length > cap && (
            <button type="button" className="btn df-more" onClick={() => setCap(cap + LINE_CAP)}>
              Show {Math.min(LINE_CAP, f.lines.length - cap)} more lines ({f.lines.length - cap} hidden)
            </button>
          )}
        </div>
      )}
    </section>
  );
}

/** Unified diff viewer: per-file sections with line numbers and +/- colouring. Text only. */
export function DiffViewer({ d }: { d: DiffResponse }) {
  const files = useMemo(() => parseDiff(d.diff), [d.diff]);
  const totalLines = useMemo(() => files.reduce((n, f) => n + f.lines.length, 0), [files]);
  const base =
    d.base_kind === "previous_checkpoint" ? "the previous checkpoint" : d.base_kind === "seed" ? "the seed commit" : d.base_kind === "root" ? "an empty tree (whole tree shown)" : "a chosen base";
  if (!d.available) return <Notice tone="warn">No git view for this checkpoint: {d.reason ?? "unavailable"}.</Notice>;
  return (
    <div>
      <p className="muted df-intro">
        Changes from {base} to <span className="mono">{d.head?.slice(0, 8)}</span>
        {d.base ? <> (base <span className="mono">{d.base.slice(0, 8)}</span>)</> : null}. {d.files.length} file{d.files.length === 1 ? "" : "s"} · {formatBytes(d.diff.length)}
      </p>
      {d.dirty && (
        <Notice tone="warn">
          This checkpoint also had uncommitted files that the git mirror does not contain (see the checkpoint snapshot on disk). Only committed changes are shown here.
        </Notice>
      )}
      {d.diff_truncated && <Notice tone="warn">The diff was cut at the server size limit; later files are missing.</Notice>}
      {d.files_truncated && <Notice tone="warn">The file list was cut at the server limit.</Notice>}
      {files.length === 0 ? (
        <p className="muted">{d.commits.length === 0 ? "No new commits since the previous checkpoint: this checkpoint shares its head." : "No textual changes."}</p>
      ) : (
        <>
          <div className="df-tools">
            <CopyButton text={d.diff} label="Copy diff" />
          </div>
          {files.map((f, i) => (
            <FileSection key={`${f.path}-${i}`} f={f} defaultOpen={files.length === 1 || (i === 0 && totalLines <= AUTO_OPEN_LINES)} />
          ))}
        </>
      )}
    </div>
  );
}
