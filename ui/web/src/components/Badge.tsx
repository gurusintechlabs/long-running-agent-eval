import type { ReactNode } from "react";

export type Tone = "ok" | "warn" | "bad" | "info" | "neutral";

export function Badge({
  tone = "neutral",
  live = false,
  plain = false,
  title,
  children,
}: {
  tone?: Tone;
  live?: boolean;
  plain?: boolean;
  title?: string;
  children: ReactNode;
}) {
  const cls = ["badge", `badge-${tone}`, live ? "badge-live" : "", plain ? "badge-plain" : ""].filter(Boolean);
  return (
    <span className={cls.join(" ")} title={title}>
      {children}
    </span>
  );
}

const STATE_TONE: Record<string, Tone> = {
  COMPLETED: "ok",
  BUDGET_EXHAUSTED: "warn",
  KILLED: "bad",
  INTERRUPTED: "warn",
  UNFINISHED: "neutral",
  FAILED: "bad",
  ERROR: "bad",
};

const STATE_LABEL: Record<string, string> = {
  BUDGET_EXHAUSTED: "budget exhausted",
};

export function stateTone(state: string | null | undefined): Tone {
  return (state && STATE_TONE[state]) || "info";
}

/** Run state as a coloured badge. The text always carries the meaning (colour is a hint only). */
export function StateBadge({ state, live = false }: { state: string | null | undefined; live?: boolean }) {
  if (!state) return <Badge tone="neutral">unknown</Badge>;
  const label = STATE_LABEL[state] ?? state.toLowerCase().replace(/_/g, " ");
  return (
    <Badge tone={live ? "info" : stateTone(state)} live={live} title={state}>
      {label}
    </Badge>
  );
}
