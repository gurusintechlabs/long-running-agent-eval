import type { ReactNode } from "react";
import { ApiAuthError } from "../api/client";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state-box" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <span className="visually-hidden">{label}</span>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state-box">
      <div className="state-title">{title}</div>
      {children && <div className="state-text">{children}</div>}
      {action}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  error,
  onRetry,
}: {
  title?: string;
  error?: Error | null;
  onRetry?: () => void;
}) {
  const detail = error && !(error instanceof ApiAuthError) ? error.message : null;
  return (
    <div className="state-box state-error" role="alert">
      <div className="state-title">{title}</div>
      {detail && <div className="state-detail">{detail}</div>}
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
