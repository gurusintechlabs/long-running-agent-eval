const DASH = "–";

export function formatDuration(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return DASH;
  const total = Math.max(0, Math.round(s));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
}

export function formatUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return `$${v.toFixed(v >= 100 ? 0 : 2)}`;
}

export function formatTokens(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}k`;
  return String(Math.round(v));
}

export function formatNumber(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return DASH;
  return Number.isInteger(v) ? String(v) : v.toFixed(digits);
}

/** Epoch seconds -> "2026-10-24 14:03" in the browser's local time. */
export function formatDateTime(epoch: number | null | undefined): string {
  if (epoch == null || !Number.isFinite(epoch)) return DASH;
  const d = new Date(epoch * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function shortSha(sha: string | null | undefined, n = 8): string {
  return sha ? sha.slice(0, n) : DASH;
}

export function ageLabel(epoch: number | null | undefined, now = Date.now() / 1000): string {
  if (epoch == null) return DASH;
  const d = Math.max(0, now - epoch);
  if (d < 90) return "just now";
  if (d < 5400) return `${Math.round(d / 60)} min ago`;
  if (d < 129600) return `${Math.round(d / 3600)} h ago`;
  return `${Math.round(d / 86400)} d ago`;
}

export const EMPTY = DASH;
