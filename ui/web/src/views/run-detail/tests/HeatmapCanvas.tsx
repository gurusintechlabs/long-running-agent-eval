import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { TestPoint } from "../../../api";
import { formatClock } from "../../../lib/text";
import type { Palette } from "../common/colors";
import { cellFlips, OUTCOME_LABEL, stageBands, type RowItem } from "./heatmapModel";

const HEADER_H = 34;
const TIER_H = 16;
const MIN_CELL_W = 11;

export interface HoverInfo {
  testId: string;
  tier: string;
  outcome: string;
  flip: "regression" | "recovery" | null;
  point: TestPoint;
  x: number;
  y: number;
}

interface Layout {
  rowH: number;
  rowTop: number[]; // y (below header) of each row
  total: number;
}

export function layoutRows(rows: RowItem[]): Layout {
  const n = rows.filter((r) => r.type === "test").length;
  const rowH = n <= 300 ? 11 : n <= 1500 ? 6 : 3;
  const rowTop: number[] = [];
  let y = 0;
  for (const r of rows) {
    rowTop.push(y);
    y += r.type === "tier" ? TIER_H : rowH;
  }
  return { rowH, rowTop, total: y };
}

function colorOf(c: string, p: Palette): string | null {
  switch (c) {
    case "p":
      return p.ok;
    case "f":
      return p.bad;
    case "e":
      return p.warn;
    case "s":
      return p.neutral;
    default:
      return null;
  }
}

/**
 * Tests x time-points outcome grid drawn on one canvas, only the visible slice (so 5000 tests x 60 points
 * costs the same as a screenful). Scrolls natively; a sticky canvas is repainted on scroll/resize/hover.
 */
export function HeatmapCanvas({
  rows,
  points,
  palette,
  height = 480,
  onHover,
}: {
  rows: RowItem[];
  points: TestPoint[];
  palette: Palette;
  height?: number;
  onHover?: (h: HoverInfo | null) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 800, h: height });
  const hover = useRef<{ row: number; col: number } | null>(null);
  const raf = useRef(0);

  const layout = useMemo(() => layoutRows(rows), [rows]);
  const flips = useMemo(() => rows.map((r) => (r.type === "test" ? cellFlips(r.test.cells) : [])), [rows]);
  const bands = useMemo(() => stageBands(points), [points]);
  const cellW = Math.max(MIN_CELL_W, Math.floor(size.w / Math.max(points.length, 1)));
  const contentW = Math.max(size.w, cellW * points.length);

  const draw = useCallback(() => {
    const el = canvas.current;
    const sc = scroller.current;
    if (!el || !sc) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const { w, h } = size;
    if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) {
      el.width = Math.round(w * dpr);
      el.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = palette.surface;
    ctx.fillRect(0, 0, w, h);
    const sl = sc.scrollLeft;
    const st = sc.scrollTop;
    const c0 = Math.max(0, Math.floor(sl / cellW));
    const c1 = Math.min(points.length - 1, Math.ceil((sl + w) / cellW));
    const gap = cellW >= 6 ? 1 : 0;

    // body: rows
    const bodyTop = HEADER_H - st;
    // first visible row (binary search on rowTop)
    let lo = 0;
    let hi = rows.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (layout.rowTop[mid] + (rows[mid].type === "tier" ? TIER_H : layout.rowH) <= st) lo = mid + 1;
      else hi = mid;
    }
    ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
    ctx.textBaseline = "middle";
    for (let i = lo; i < rows.length; i++) {
      const y = layout.rowTop[i] + bodyTop;
      if (y > h) break;
      const r = rows[i];
      if (r.type === "tier") {
        ctx.fillStyle = palette.surface2;
        ctx.fillRect(0, y, w, TIER_H);
        ctx.fillStyle = palette.text;
        ctx.fillText(`Tier ${r.tier}  ·  ${r.count} tests`, 8, y + TIER_H / 2);
        continue;
      }
      const cells = r.test.cells;
      for (let c = c0; c <= c1; c++) {
        const col = colorOf(cells[c] ?? "-", palette);
        const x = c * cellW - sl;
        if (!col) {
          ctx.fillStyle = palette.surface2;
          ctx.fillRect(x, y, cellW - gap, layout.rowH - (layout.rowH > 4 ? 1 : 0));
          continue;
        }
        ctx.fillStyle = col;
        ctx.fillRect(x, y, cellW - gap, layout.rowH - (layout.rowH > 4 ? 1 : 0));
      }
      // flip markers
      for (const f of flips[i]) {
        if (f.col < c0 || f.col > c1) continue;
        const x = f.col * cellW - sl;
        ctx.strokeStyle = f.kind === "regression" ? palette.text : palette.accent;
        ctx.lineWidth = f.kind === "regression" ? 2 : 1.5;
        ctx.strokeRect(x + 0.5, y + 0.5, cellW - gap - 1, Math.max(layout.rowH - 2, 2));
      }
    }

    // stage separators
    ctx.strokeStyle = palette.border;
    ctx.lineWidth = 1;
    for (const b of bands) {
      const x = b.from * cellW - sl - 0.5;
      if (x < -1 || x > w) continue;
      ctx.beginPath();
      ctx.moveTo(x, HEADER_H);
      ctx.lineTo(x, h);
      ctx.stroke();
    }

    // hover highlight
    const hv = hover.current;
    if (hv && hv.col >= c0 && hv.col <= c1 && rows[hv.row]) {
      const y = layout.rowTop[hv.row] + bodyTop;
      ctx.strokeStyle = palette.text;
      ctx.lineWidth = 2;
      ctx.strokeRect(hv.col * cellW - sl + 1, y, cellW - 2, Math.max(layout.rowH, 3));
    }

    // sticky header: stage bands + time labels
    ctx.fillStyle = palette.surface;
    ctx.fillRect(0, 0, w, HEADER_H);
    bands.forEach((b, bi) => {
      const x0 = b.from * cellW - sl;
      const x1 = (b.to + 1) * cellW - sl;
      if (x1 < 0 || x0 > w) return;
      ctx.fillStyle = bi % 2 ? palette.surface2 : palette.grid;
      ctx.globalAlpha = 0.7;
      ctx.fillRect(x0, 0, x1 - x0 - 1, 17);
      ctx.globalAlpha = 1;
      ctx.fillStyle = palette.text;
      ctx.textAlign = "left";
      if (x1 - x0 > 22) ctx.fillText(b.stage == null ? "?" : `s${b.stage}`, Math.max(x0, 0) + 4, 9);
    });
    const step = Math.max(1, Math.ceil(46 / cellW));
    ctx.fillStyle = palette.muted;
    for (let c = c0; c <= c1; c++) {
      const x = c * cellW - sl;
      const p = points[c];
      if (p.point === "checkpoint") {
        ctx.fillStyle = palette.info;
        ctx.beginPath();
        ctx.moveTo(x + cellW / 2, 20);
        ctx.lineTo(x + cellW / 2 + 4, 24);
        ctx.lineTo(x + cellW / 2, 28);
        ctx.lineTo(x + cellW / 2 - 4, 24);
        ctx.fill();
      }
      if (c % step === 0) {
        ctx.fillStyle = palette.muted;
        ctx.fillText(formatClock(p.t_s), x + 2, 31);
      }
    }
    ctx.strokeStyle = palette.border;
    ctx.beginPath();
    ctx.moveTo(0, HEADER_H - 0.5);
    ctx.lineTo(w, HEADER_H - 0.5);
    ctx.stroke();
  }, [size, palette, rows, layout, flips, bands, points, cellW]);

  const schedule = useCallback(() => {
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(draw);
  }, [draw]);

  useEffect(() => {
    schedule();
    return () => cancelAnimationFrame(raf.current);
  }, [schedule]);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => setSize({ w: Math.max(el.clientWidth, 200), h: height });
    measure();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [height]);

  const locate = (e: React.MouseEvent) => {
    const sc = scroller.current;
    if (!sc) return null;
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const x = e.clientX - rect.left + sc.scrollLeft;
    const y = e.clientY - rect.top + sc.scrollTop - HEADER_H;
    if (y < 0) return null;
    const col = Math.floor(x / cellW);
    if (col < 0 || col >= points.length) return null;
    let lo = 0;
    let hi = rows.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (layout.rowTop[mid] <= y) lo = mid;
      else hi = mid - 1;
    }
    const r = rows[lo];
    if (!r || r.type !== "test") return null;
    return { row: lo, col, r };
  };

  const move = (e: React.MouseEvent) => {
    const hit = locate(e);
    if (!hit) {
      if (hover.current) {
        hover.current = null;
        onHover?.(null);
        schedule();
      }
      return;
    }
    const prev = hover.current;
    hover.current = { row: hit.row, col: hit.col };
    const o = hit.r.type === "test" ? hit.r.test.cells[hit.col] ?? "-" : "-";
    const wrap = scroller.current!.getBoundingClientRect();
    onHover?.({
      testId: hit.r.type === "test" ? hit.r.test.id : "",
      tier: hit.r.type === "test" ? hit.r.test.tier ?? "" : "",
      outcome: OUTCOME_LABEL[o] ?? o,
      flip: flips[hit.row].find((f) => f.col === hit.col)?.kind ?? null,
      point: points[hit.col],
      x: e.clientX - wrap.left,
      y: e.clientY - wrap.top,
    });
    if (!prev || prev.row !== hit.row || prev.col !== hit.col) schedule();
  };

  const leave = () => {
    hover.current = null;
    onHover?.(null);
    schedule();
  };

  return (
    <div className="hm-scroll" ref={scroller} style={{ height }} onScroll={schedule}>
      <div style={{ width: contentW, height: HEADER_H + layout.total }}>
        <canvas
          ref={canvas}
          className="hm-canvas"
          style={{ width: size.w, height: size.h }}
          onMouseMove={move}
          onMouseLeave={leave}
          role="img"
          aria-label={`Test outcome heatmap: ${rows.filter((r) => r.type === "test").length} tests by ${points.length} time points. The flips list below has the same information as text.`}
        />
      </div>
    </div>
  );
}
