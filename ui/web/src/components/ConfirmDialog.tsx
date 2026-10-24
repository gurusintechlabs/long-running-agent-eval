import { useEffect, useRef, type ReactNode } from "react";
import "./dialog.css";

/**
 * Small modal confirmation. Escape cancels, Tab stays inside, focus returns to the opener.
 * Content is plain React children (text), never HTML strings.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  busy = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  children?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const inBody = el?.querySelector<HTMLElement>(".dialog-body input, .dialog-body select, .dialog-body textarea");
    (inBody ?? el?.querySelector<HTMLElement>("[data-autofocus]"))?.focus();
    return () => opener?.focus?.();
  }, []);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onCancel();
    } else if (e.key === "Tab") {
      const els = [...(ref.current?.querySelectorAll<HTMLElement>("input, select, textarea, button:not(:disabled)") ?? [])];
      if (els.length === 0) return;
      const i = els.indexOf(document.activeElement as HTMLElement);
      if (e.shiftKey && i <= 0) {
        e.preventDefault();
        els[els.length - 1].focus();
      } else if (!e.shiftKey && i === els.length - 1) {
        e.preventDefault();
        els[0].focus();
      }
    }
  };

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div ref={ref} className="dialog" role="dialog" aria-modal="true" aria-label={title} onKeyDown={onKey}>
        <h2 className="dialog-title">{title}</h2>
        <div className="dialog-body">{children}</div>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button
            type="button"
            data-autofocus
            className={`btn btn-primary${danger ? " btn-danger" : ""}`}
            onClick={onConfirm}
            disabled={busy || confirmDisabled}
          >
            {busy ? "Working..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
