import { useCallback, useEffect, useRef, useState } from "react";
import { ApiAuthError } from "./client";

export interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  /** True only for the first load (no data yet). Background refreshes keep showing the old data. */
  loading: boolean;
  reload: () => void;
}

/**
 * Run `fetcher` on mount and whenever `deps` change. When `refreshMs` returns a number the data is
 * re-fetched on that interval (return null to stop polling), without flashing a spinner.
 */
export function useAsync<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  refreshMs?: (data: T | null) => number | null,
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const refreshRef = useRef(refreshMs);
  refreshRef.current = refreshMs;

  useEffect(() => {
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let first = true;
    setData(null);
    setError(null);
    setLoading(true);

    const run = async () => {
      try {
        const d = await fetcherRef.current(ctl.signal);
        if (ctl.signal.aborted) return;
        setData(d);
        setError(null);
        setLoading(false);
        first = false;
        const ms = refreshRef.current?.(d) ?? null;
        if (ms) timer = setTimeout(run, ms);
      } catch (e) {
        if (ctl.signal.aborted) return;
        setError(e instanceof Error ? e : new Error(String(e)));
        setLoading(false);
        // Keep polling through transient errors, but never hammer after a 401.
        const ms = !(e instanceof ApiAuthError) && !first ? refreshRef.current?.(null) ?? null : null;
        if (ms) timer = setTimeout(run, ms);
      }
    };
    void run();
    return () => {
      ctl.abort();
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
