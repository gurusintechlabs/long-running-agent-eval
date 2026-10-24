import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type Ref } from "react";

// A small variable-height virtual list. Rows are absolutely positioned inside a spacer of the total height;
// each rendered row is measured with one shared ResizeObserver, unmeasured rows use `estimate`. Scroll
// anchoring keeps the first visible row where it is when rows above change height or are dropped, and
// `follow` pins the view to the bottom (the "now" edge) without jumps.

export interface VirtualHandle {
  scrollToBottom: () => void;
  scrollToTop: () => void;
}

const BOTTOM_SLACK = 28;

export function VirtualList<T>({
  items,
  keyOf,
  render,
  estimate = 52,
  overscan = 8,
  follow,
  onAtBottomChange,
  handleRef,
  label,
  fallbackViewport = 640,
  onNearEnd,
}: {
  items: readonly T[];
  keyOf: (item: T) => string;
  render: (item: T, index: number) => ReactNode;
  estimate?: number;
  overscan?: number;
  /** Stick to the bottom while true. */
  follow: boolean;
  onAtBottomChange?: (atBottom: boolean) => void;
  handleRef?: Ref<VirtualHandle>;
  label: string;
  /** Viewport height to assume when the browser reports 0 (tests). */
  fallbackViewport?: number;
  /** Called when the view is within a screen of the end of the list (replay paging). */
  onNearEnd?: () => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const heights = useRef(new Map<string, number>());
  const [, setMeasureTick] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(0);
  const anchor = useRef<{ key: string; delta: number } | null>(null);
  const atBottom = useRef(true);
  const raf = useRef(0);
  const followRef = useRef(follow);
  followRef.current = follow;

  const keys = useMemo(() => items.map(keyOf), [items, keyOf]);
  // heights.current is read during render on purpose: it is a measurement cache and the tick state re-renders.
  const { offsets, total } = (() => {
    const off = new Float64Array(keys.length + 1);
    for (let i = 0; i < keys.length; i++) off[i + 1] = off[i] + (heights.current.get(keys[i]) ?? estimate);
    return { offsets: off, total: off[keys.length] };
  })();

  const vp = viewport || fallbackViewport;
  // first visible index by binary search
  let lo = 0;
  let hi = keys.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (offsets[mid + 1] <= scrollTop) lo = mid + 1;
    else hi = mid;
  }
  const first = Math.max(0, lo - overscan);
  let last = lo;
  while (last < keys.length && offsets[last] < scrollTop + vp) last++;
  last = Math.min(keys.length, last + overscan);

  const bump = useCallback(() => {
    if (raf.current) return;
    raf.current = requestAnimationFrame(() => {
      raf.current = 0;
      setMeasureTick((t) => t + 1);
    });
  }, []);

  const ro = useRef<ResizeObserver | null>(null);
  if (ro.current === null && typeof ResizeObserver === "function") {
    ro.current = new ResizeObserver((entries) => {
      let changed = false;
      for (const en of entries) {
        const el = en.target as HTMLElement;
        const key = el.dataset.vkey;
        if (!key) continue;
        const h = Math.round(el.getBoundingClientRect().height);
        if (h > 0 && heights.current.get(key) !== h) {
          heights.current.set(key, h);
          changed = true;
        }
      }
      if (changed) bump();
    });
  }
  useEffect(() => {
    const o = ro.current;
    return () => {
      o?.disconnect();
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, []);

  // viewport size
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    setViewport(el.clientHeight);
    const r = new ResizeObserver(() => setViewport(el.clientHeight));
    r.observe(el);
    return () => r.disconnect();
  }, []);

  const scrollToBottom = useCallback(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);
  useImperativeHandle(handleRef, () => ({ scrollToBottom, scrollToTop: () => { if (scroller.current) scroller.current.scrollTop = 0; } }), [scrollToBottom]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const st = el.scrollTop;
    setScrollTop(st);
    const bottom = el.scrollHeight - st - el.clientHeight <= BOTTOM_SLACK;
    if (bottom !== atBottom.current) {
      atBottom.current = bottom;
      onAtBottomChange?.(bottom);
    }
    // remember the first visible row for anchoring
    let i = 0;
    let h = keys.length;
    while (i < h) {
      const mid = (i + h) >> 1;
      if (offsets[mid + 1] <= st) i = mid + 1;
      else h = mid;
    }
    if (i < keys.length) anchor.current = { key: keys[i], delta: st - offsets[i] };
    if (onNearEnd && el.scrollHeight - st - el.clientHeight < el.clientHeight * 1.5) onNearEnd();
  };

  // after every layout: pin to bottom when following, else restore the anchor
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (followRef.current) {
      if (el.scrollHeight - el.scrollTop - el.clientHeight > 1) el.scrollTop = el.scrollHeight;
      return;
    }
    const a = anchor.current;
    if (!a) return;
    const idx = keys.indexOf(a.key);
    if (idx < 0) return;
    const want = offsets[idx] + a.delta;
    if (Math.abs(el.scrollTop - want) > 1) el.scrollTop = want;
  });

  // a near-end check also when the list is short (fits without scrolling)
  useEffect(() => {
    const el = scroller.current;
    if (onNearEnd && el && el.scrollHeight - el.scrollTop - el.clientHeight < el.clientHeight * 1.5) onNearEnd();
  }, [onNearEnd, total, keys.length]);

  return (
    <div ref={scroller} className="vl" onScroll={onScroll} tabIndex={0} role="log" aria-label={label} aria-live="off">
      <div className="vl-spacer" style={{ height: total }}>
        {keys.slice(first, last).map((k, n) => {
          const i = first + n;
          return (
            <div
              key={k}
              className="vl-item"
              data-vkey={k}
              style={{ top: offsets[i] }}
              ref={(el) => {
                if (el && ro.current) ro.current.observe(el);
              }}
            >
              {render(items[i], i)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
