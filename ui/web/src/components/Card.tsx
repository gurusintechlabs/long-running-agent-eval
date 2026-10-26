import type { ReactNode } from "react";

export function Card({
  title,
  actions,
  flush = false,
  children,
  className = "",
}: {
  title?: ReactNode;
  actions?: ReactNode;
  flush?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`.trim()}>
      {(title || actions) && (
        <header className="card-head">
          {title ? <h2>{title}</h2> : <span />}
          {actions}
        </header>
      )}
      <div className={flush ? "card-body-flush" : "card-body"}>{children}</div>
    </section>
  );
}
