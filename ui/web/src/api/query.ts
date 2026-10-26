/** Build `?a=1&b=x` from a params object; null/undefined/false/"" are skipped. Values are URL-encoded. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v == null || v === false || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}
