import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import "./dialog.css";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Modal dialog: role=dialog, aria-modal, focus moves in, Tab/Shift+Tab stay inside, Esc closes, focus
 * returns to the opener. A click on the backdrop does NOT close it (a misclick must not lose a typed
 * confirmation). All content is the caller's React children (text only, UI-5).
 */
export function Dialog({
  title,
  onClose,
  children,
  footer,
  tone = "default",
  closeLabel = "Close",
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  tone?: "default" | "danger";
  closeLabel?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const node = ref.current;
    if (!node) return;
    // Focus the first control inside the body; fall back to the dialog itself.
    const first = node.querySelector<HTMLElement>('[data-autofocus], input, select, textarea') ?? node.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? node).focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = [...node.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === firstEl || active === node)) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && active === lastEl) {
        e.preventDefault();
        firstEl.focus();
      } else if (!node.contains(active)) {
        e.preventDefault();
        firstEl.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);

  return createPortal(
    <div className="dialog-backdrop">
      <div ref={ref} className={`dialog dialog-${tone}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <header className="dialog-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="btn dialog-x" onClick={onClose} aria-label={closeLabel}>
            {"×"}
          </button>
        </header>
        <div className="dialog-body">{children}</div>
        {footer && <footer className="dialog-foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
