import { useRef } from "react";

/**
 * ECharts tooltips are HTML. Any custom tooltip formatter MUST pass every piece of data-derived text
 * through this first (UI-5): `<img onerror>` in a test id has to come out as visible text.
 */
export function escapeHtml(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function clip(s: string | null | undefined, n: number): string {
  if (!s) return "";
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

/** Seconds since run start as h:mm:ss (m:ss under an hour). Null-safe. */
export function formatClock(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return "–";
  const neg = s < 0;
  const t = Math.round(Math.abs(s));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${neg ? "-" : ""}${h > 0 ? `${h}:${p(m)}` : String(m)}:${p(sec)}`;
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "–";
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} kB`;
  return `${n} B`;
}

/** Returns the previous object while a polled value is deep-equal, so memoised charts keep their zoom. */
export function useStable<T>(value: T | null): T | null {
  const ref = useRef<{ key: string; value: T | null }>({ key: "", value: null });
  if (value == null) return value;
  const key = JSON.stringify(value);
  if (key !== ref.current.key) ref.current = { key, value };
  return ref.current.value;
}
