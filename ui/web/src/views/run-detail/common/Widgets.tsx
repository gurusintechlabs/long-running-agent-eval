import { useEffect, useRef, useState, type ReactNode } from "react";
import { formatBytes } from "../../../lib/text";

/** Copies `text` to the clipboard. Falls back silently (status text says so) when the API is blocked. */
export function CopyButton({ text, label = "Copy" }: { text: string | (() => string); label?: string }) {
  const [state, setState] = useState<"idle" | "ok" | "fail">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const run = async () => {
    try {
      await navigator.clipboard.writeText(typeof text === "function" ? text() : text);
      setState("ok");
    } catch {
      setState("fail");
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 1600);
  };
  return (
    <button type="button" className="btn btn-small" onClick={() => void run()} aria-live="polite">
      {state === "ok" ? "Copied" : state === "fail" ? "Copy failed" : label}
    </button>
  );
}

/**
 * Text (always a React text child, never HTML) that is collapsed past `max` characters with a toggle.
 * The full string is already in memory; this only limits what is laid out.
 */
export function ExpandableText({
  text,
  max = 600,
  className = "",
  defaultOpen = false,
  note,
}: {
  text: string;
  max?: number;
  className?: string;
  defaultOpen?: boolean;
  note?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const long = text.length > max;
  const shown = open || !long ? text : text.slice(0, max);
  return (
    <div className="xtext">
      <pre className={`xtext-pre ${className}`.trim()}>
        {shown}
        {!open && long ? "…" : ""}
      </pre>
      <div className="xtext-bar">
        {long && (
          <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Collapse" : `Show all (${formatBytes(text.length)})`}
          </button>
        )}
        <CopyButton text={text} />
        {note}
      </div>
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "bad"; children: ReactNode }) {
  return (
    <div className={`notice notice-${tone}`} role={tone === "bad" ? "alert" : "note"}>
      {children}
    </div>
  );
}

/** Small toggle chip used for legends and filters. */
export function Chip({
  on,
  onClick,
  children,
  title,
  swatch,
}: {
  on: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
  swatch?: string;
}) {
  return (
    <button type="button" className={`chip${on ? " chip-on" : ""}`} aria-pressed={on} title={title} onClick={onClick}>
      {swatch && <span className="chip-swatch" style={{ background: swatch }} aria-hidden="true" />}
      {children}
    </button>
  );
}
