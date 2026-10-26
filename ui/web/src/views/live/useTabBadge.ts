import { useEffect, useRef } from "react";

const PREFIX = /^\(\d+!\) /;

/** Tab title with a "(n!) " prefix. Visual only: no sound, no Notification API (design section 9). */
export function applyBadge(title: string, n: number): string {
  const base = title.replace(PREFIX, "");
  return n > 0 ? `(${n}!) ${base}` : base;
}

/**
 * `total` is the current number of violations plus kills (null while unknown). Increases seen after the
 * first value count as "new"; they show in the tab title only while the tab is hidden, and clear once the
 * tab is visible again.
 */
export function useTabBadge(total: number | null) {
  const baseline = useRef<number | null>(null);
  const unseen = useRef(0);
  const last = useRef<number | null>(null);

  useEffect(() => {
    if (total == null) return;
    if (baseline.current == null) {
      baseline.current = total;
      last.current = total;
      return;
    }
    const delta = total - (last.current ?? total);
    last.current = total;
    if (delta > 0 && document.hidden) {
      unseen.current += delta;
      document.title = applyBadge(document.title, unseen.current);
    }
  }, [total]);

  useEffect(() => {
    const onVis = () => {
      if (!document.hidden && unseen.current > 0) {
        unseen.current = 0;
        document.title = applyBadge(document.title, 0);
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      if (unseen.current > 0) document.title = applyBadge(document.title, 0);
    };
  }, []);
}
