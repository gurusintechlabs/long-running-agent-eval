import { useCallback, useEffect, useRef, useState } from "react";
import { ApiAuthError, transcriptApi, type TranscriptItem, type TranscriptParams, type TranscriptResponse } from "../../../api";

export interface TranscriptFilters {
  tools: string[];
  errorsOnly: boolean;
  q: string;
  kind: string[];
}

export interface Target {
  cursor?: string | null;
  t_s?: number | null;
}

const PAGE = 100;
const CTX_BEFORE = 20;
const CTX_AFTER = 5;
const MORE = 40;

interface State {
  items: TranscriptItem[];
  next: string | null;
  eof: boolean;
  anchor: string | null;
  mode: "page" | "around";
  total: number;
  tools: TranscriptResponse["tools"];
  loading: boolean;
  more: boolean;
  error: Error | null;
  before: number;
}

const INIT: State = { items: [], next: null, eof: false, anchor: null, mode: "page", total: 0, tools: [], loading: true, more: false, error: null, before: CTX_BEFORE };

/**
 * Transcript paging state. A target (cursor or t_s) opens an "around" window ("20 before, 5 after");
 * otherwise items are paged from the start with "load more". Filters apply inside both.
 */
export function useTranscript(runId: string, filters: TranscriptFilters, target: Target) {
  const [s, setS] = useState<State>(INIT);
  const [tick, setTick] = useState(0);
  const ctl = useRef<AbortController | null>(null);
  const key = JSON.stringify([runId, filters, target, tick]);
  const aroundParams = (before: number): TranscriptParams => ({
    around: target.cursor ?? undefined,
    around_t_s: target.cursor ? undefined : target.t_s,
    before,
    after_n: CTX_AFTER,
  });
  const base = (): TranscriptParams => ({
    tool: filters.tools,
    kind: filters.kind,
    q: filters.q || undefined,
    errors_only: filters.errorsOnly,
  });
  const hasTarget = target.cursor != null || target.t_s != null;

  useEffect(() => {
    ctl.current?.abort();
    const c = new AbortController();
    ctl.current = c;
    setS((p) => ({ ...INIT, tools: p.tools, loading: true }));
    const params: TranscriptParams = hasTarget ? { ...base(), ...aroundParams(CTX_BEFORE) } : { ...base(), limit: PAGE };
    transcriptApi
      .list(runId, params, c.signal)
      .then((r) => {
        if (c.signal.aborted) return;
        setS({ items: r.items, next: r.next, eof: r.eof, anchor: r.anchor, mode: r.mode, total: r.total_items, tools: r.tools, loading: false, more: false, error: null, before: CTX_BEFORE });
      })
      .catch((e: unknown) => {
        if (c.signal.aborted) return;
        setS((p) => ({ ...p, loading: false, error: e instanceof Error ? e : new Error(String(e)) }));
      });
    return () => c.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  /** Append the next page (page mode: `next`; around mode: items after the last one shown). */
  const loadMore = useCallback((force = false) => {
    setS((p) => {
      if (p.more || (p.eof && !force)) return p;
      const after = p.mode === "around" ? p.items[p.items.length - 1]?.cursor : p.next;
      if (!after) return p;
      const c = new AbortController();
      ctl.current = c;
      transcriptApi
        .list(runId, { ...base(), after, limit: p.mode === "around" ? MORE : PAGE }, c.signal)
        .then((r) =>
          setS((q) => ({ ...q, items: [...q.items, ...r.items], next: r.next ?? q.next, eof: r.eof, total: r.total_items, more: false })),
        )
        .catch((e: unknown) => {
          if (e instanceof ApiAuthError || c.signal.aborted) return;
          setS((q) => ({ ...q, more: false, error: e instanceof Error ? e : new Error(String(e)) }));
        });
      return { ...p, more: true };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, key]);

  /** Around mode: widen the window upwards (re-query with a larger `before`). */
  const loadEarlier = useCallback(() => {
    setS((p) => {
      if (p.more || p.mode !== "around") return p;
      const before = p.before + MORE;
      const c = new AbortController();
      ctl.current = c;
      const had = p.items.length;
      transcriptApi
        .list(runId, { ...base(), ...aroundParams(before) }, c.signal)
        .then((r) => {
          // keep any items already appended after the window
          setS((q) => {
            const lastNew = r.items[r.items.length - 1]?.cursor;
            const tail = lastNew ? q.items.slice(q.items.findIndex((i) => i.cursor === lastNew) + 1) : [];
            return { ...q, items: [...r.items, ...(had > 0 ? tail : [])], before, more: false };
          });
        })
        .catch(() => setS((q) => ({ ...q, more: false })));
      return { ...p, more: true };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, key]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...s, reload, loadMore, loadEarlier, hasTarget };
}
