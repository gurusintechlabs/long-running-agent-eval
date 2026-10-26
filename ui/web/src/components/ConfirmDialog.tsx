import type { ReactNode } from "react";
import { Dialog } from "./Dialog";

/**
 * Small confirmation modal built on {@link Dialog} (focus trap, Esc, focus restore). Content is plain
 * React children (text), never HTML strings.
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
  return (
    <Dialog
      title={title}
      onClose={onCancel}
      tone={danger ? "danger" : "default"}
      footer={
        <>
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
        </>
      }
    >
      {children}
    </Dialog>
  );
}
