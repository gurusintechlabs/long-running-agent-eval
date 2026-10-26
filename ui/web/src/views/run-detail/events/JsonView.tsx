import { useState } from "react";

const CHILD_STEP = 60;
const STR_MAX = 400;

/** Collapsible JSON tree. Every key and value is a React text child: nothing here is ever HTML. */
export function JsonView({ value, openDepth = 2 }: { value: unknown; openDepth?: number }) {
  return (
    <div className="json" role="tree" aria-label="JSON payload">
      <Node name={null} value={value} depth={0} openDepth={openDepth} last />
    </div>
  );
}

function Scalar({ value }: { value: unknown }) {
  const [open, setOpen] = useState(false);
  if (typeof value === "string") {
    const long = value.length > STR_MAX;
    const shown = long && !open ? value.slice(0, STR_MAX) : value;
    return (
      <span className="j-str">
        {JSON.stringify(shown).replace(/"$/, long && !open ? "" : '"')}
        {long && !open && "…"}
        {long && (
          <button type="button" className="link-btn j-more" onClick={() => setOpen(!open)}>
            {open ? "collapse" : `show all ${value.length.toLocaleString("en-US")} chars`}
          </button>
        )}
      </span>
    );
  }
  if (value === null) return <span className="j-null">null</span>;
  if (typeof value === "number") return <span className="j-num">{String(value)}</span>;
  if (typeof value === "boolean") return <span className="j-bool">{String(value)}</span>;
  return <span>{String(value)}</span>;
}

function Node({ name, value, depth, openDepth, last }: { name: string | number | null; value: unknown; depth: number; openDepth: number; last: boolean }) {
  const isObj = value !== null && typeof value === "object";
  const [open, setOpen] = useState(depth < openDepth);
  const [shown, setShown] = useState(CHILD_STEP);
  const key = name == null ? null : <span className="j-key">{typeof name === "number" ? name : JSON.stringify(name)}: </span>;
  const comma = last ? "" : ",";
  if (!isObj) {
    return (
      <div className="j-row" role="treeitem" aria-selected="false">
        {key}
        <Scalar value={value} />
        {comma}
      </div>
    );
  }
  const arr = Array.isArray(value);
  const entries: [string | number, unknown][] = arr ? (value as unknown[]).map((v, i) => [i, v]) : Object.entries(value as Record<string, unknown>);
  const [o, c] = arr ? ["[", "]"] : ["{", "}"];
  if (entries.length === 0) {
    return (
      <div className="j-row" role="treeitem" aria-selected="false">
        {key}
        {o}
        {c}
        {comma}
      </div>
    );
  }
  return (
    <div role="treeitem" aria-expanded={open} aria-selected="false">
      <div className="j-row">
        <button type="button" className="j-toggle" aria-label={open ? "Collapse" : "Expand"} onClick={() => setOpen(!open)}>
          {open ? "▾" : "▸"}
        </button>
        {key}
        {o}
        {!open && (
          <span className="muted">
            {" "}
            {entries.length} {arr ? "items" : "keys"}{" "}
          </span>
        )}
        {!open && c}
        {!open && comma}
      </div>
      {open && (
        <div className="j-children" role="group">
          {entries.slice(0, shown).map(([k, v], i) => (
            <Node key={String(k)} name={arr ? null : k} value={v} depth={depth + 1} openDepth={openDepth} last={i === entries.length - 1 && entries.length <= shown} />
          ))}
          {entries.length > shown && (
            <div className="j-row">
              <button type="button" className="link-btn" onClick={() => setShown(shown + CHILD_STEP)}>
                show {Math.min(CHILD_STEP, entries.length - shown)} more of {entries.length - shown}
              </button>
            </div>
          )}
        </div>
      )}
      {open && (
        <div className="j-row">
          {c}
          {comma}
        </div>
      )}
    </div>
  );
}
