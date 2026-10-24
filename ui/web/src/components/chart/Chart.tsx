import { useEffect, useRef } from "react";
import { echarts, type ChartOption, type ECharts } from "./echarts";

export interface ChartClickParams {
  seriesName?: string;
  seriesIndex?: number;
  dataIndex?: number;
  data?: unknown;
  componentType?: string;
}

/**
 * Thin ECharts wrapper: creates the instance, keeps it sized with a ResizeObserver, applies `option`
 * whenever it changes, and disposes on unmount. Build `option` with `useChartTheme()` so colours follow
 * the OS theme (changing the theme changes `option`, which re-applies it).
 */
export function Chart({
  option,
  height = 220,
  label,
  onClick,
}: {
  option: ChartOption;
  height?: number;
  /** Accessible name (charts are canvas, so this is what a screen reader hears). */
  label: string;
  /** Called with ECharts' click params (the clicked datum is `params.data`). Optional, additive. */
  onClick?: (params: ChartClickParams) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const inst = useRef<ECharts | null>(null);
  const clickRef = useRef(onClick);
  clickRef.current = onClick;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const chart = echarts.init(el, undefined, { renderer: "canvas" });
    inst.current = chart;
    chart.on("click", (p: unknown) => clickRef.current?.(p as ChartClickParams));
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(() => chart.resize()) : null;
    ro?.observe(el);
    return () => {
      ro?.disconnect();
      chart.dispose();
      inst.current = null;
    };
  }, []);

  useEffect(() => {
    inst.current?.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={host} className="chart" style={{ height }} role="img" aria-label={label} />;
}
