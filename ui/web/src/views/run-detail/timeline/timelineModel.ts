import type { TimelineResponse } from "../../../api";
import { clip, escapeHtml, formatClock } from "../../../lib/text";
import { formatUsd } from "../../../lib/format";
import type { Palette } from "../common/colors";
import { behaviorLink, hazardLink, runTabUrl, transcriptLink, violationLink } from "../common/links";

export const LANES = ["Checkpoints", "Stages", "Compactions", "Hazards", "Behaviour", "Guardrail"] as const;
export type Lane = (typeof LANES)[number];

export interface TlEvent {
  t: number;
  lane: Lane;
  /** Short headline (first tooltip line). */
  title: string;
  /** Detail lines (agent-derived: escaped before they reach the tooltip). */
  detail: string[];
  /** In-app URL the marker deep-links to (null: nothing to open). */
  link: string | null;
  tone: "ok" | "warn" | "bad" | "info" | "neutral";
}

/** All markers of the timeline as one sorted list: the chart, the tooltip and the incident table share it. */
export function buildEvents(tl: TimelineResponse): TlEvent[] {
  const id = tl.run_id;
  const out: TlEvent[] = [];
  for (const c of tl.checkpoints) {
    if (c.t_s == null) continue;
    out.push({
      t: c.t_s,
      lane: "Checkpoints",
      title: `Checkpoint t${c.k}`,
      detail: [
        `head ${c.head_sha?.slice(0, 8) ?? "–"}${c.dirty ? " (uncommitted files)" : ""}`,
        ...(c.cumulative_cost_usd != null ? [`cumulative est. cost ${formatUsd(c.cumulative_cost_usd)}`] : []),
      ],
      link: runTabUrl(id, "checkpoints", { k: c.k }),
      tone: c.dirty ? "warn" : "info",
    });
  }
  for (const s of tl.stages) {
    if (s.t_s == null) continue;
    out.push({
      t: s.t_s,
      lane: "Stages",
      title: `Stage ${s.stage}`,
      detail: [s.kind + (s.interrupted ? " (interrupted)" : "")],
      link: transcriptLink(id, { t_s: s.t_s }),
      tone: "neutral",
    });
  }
  for (const m of tl.markers) {
    if (m.t_s == null || m.kind === "stage") continue;
    out.push({
      t: m.t_s,
      lane: "Stages",
      title: m.kind === "directive" ? "Directive" : m.kind === "env" ? "Environment" : m.kind,
      detail: [m.label],
      link: transcriptLink(id, { t_s: m.t_s }),
      tone: "info",
    });
  }
  for (const c of tl.compactions) {
    if (c.t_s == null) continue;
    out.push({
      t: c.t_s,
      lane: "Compactions",
      title: `Compaction (${c.trigger ?? "?"})`,
      detail: c.pre_tokens != null ? [`${c.pre_tokens.toLocaleString("en-US")} tokens before`] : [],
      link: transcriptLink(id, { cursor: c.cursor, t_s: c.t_s }),
      tone: "info",
    });
  }
  for (const h of tl.hazards) {
    const t = h.t_attributed_s ?? h.t_detected_s;
    if (t == null) continue;
    out.push({
      t,
      lane: "Hazards",
      title: `Hazard ${h.rule} (${h.dimension})`,
      detail: [h.evidence ?? "", ...(h.k != null ? [`checkpoint t${h.k}`] : [])].filter(Boolean),
      link: hazardLink(id, h),
      tone: "bad",
    });
  }
  for (const b of tl.behavior) {
    if (b.t_s == null) continue;
    out.push({
      t: b.t_s,
      lane: "Behaviour",
      title: `${b.detector}${b.hazard ? " (hazard)" : ""}`,
      detail: [`${b.dimension ?? ""} ${b.mode ?? ""} ${b.severity}`.trim(), b.evidence ?? ""].filter(Boolean),
      link: behaviorLink(id, b),
      tone: b.hazard ? "bad" : "warn",
    });
  }
  for (const v of tl.guardrail.violations) {
    if (v.t_s == null) continue;
    out.push({
      t: v.t_s,
      lane: "Guardrail",
      title: `${v.rule_id} (${v.severity}, ${v.action})`,
      detail: [v.evidence ?? ""].filter(Boolean),
      link: violationLink(id, v),
      tone: v.action === "kill" || v.severity === "critical" ? "bad" : "warn",
    });
  }
  const k = tl.guardrail.kill;
  if (k && k.t_s != null) {
    out.push({
      t: k.t_s,
      lane: "Guardrail",
      title: `Kill: ${k.rule_id}`,
      detail: [k.reason ?? "", k.freeze_latency_ms != null ? `froze after ${k.freeze_latency_ms.toFixed(1)} ms` : ""].filter(Boolean),
      link: transcriptLink(id, { t_s: k.t_s }),
      tone: "bad",
    });
  }
  return out.sort((a, b) => a.t - b.t);
}

const nearest = <T extends { t_s: number | null }>(rows: T[], t: number): T | null => {
  let best: T | null = null;
  let d = Infinity;
  for (const r of rows) {
    if (r.t_s == null) continue;
    const x = Math.abs(r.t_s - t);
    if (x < d) {
      d = x;
      best = r;
    }
  }
  return best;
};

/** Plain-text tooltip body for time `t` (shared by every lane: the linked tooltip). */
export function tooltipLines(tl: TimelineResponse, events: TlEvent[], t: number, tol: number): string[] {
  const lines = [`Run time ${formatClock(t)}`];
  const s = nearest(tl.series, t);
  if (s) {
    lines.push(
      `Checkpoint t${s.k} (${formatClock(s.t_s)}): est. cost ${formatUsd(s.cum_cost_usd)}, context ${s.context_fill_max != null ? `${Math.round(s.context_fill_max * 100)}%` : "–"}`,
    );
  }
  const near = events.filter((e) => Math.abs(e.t - t) <= tol && e.lane !== "Checkpoints");
  for (const e of near.slice(0, 6)) lines.push(`${e.lane}: ${e.title}${e.detail[0] ? ` | ${clip(e.detail[0], 140)}` : ""}`);
  if (near.length > 6) lines.push(`... and ${near.length - 6} more here`);
  return lines;
}

const toneColor = (p: Palette, t: TlEvent["tone"]) => p[t];

interface Datum {
  value: [number, string];
  link: string | null;
  ev: TlEvent;
}

export function buildTimelineOption(tl: TimelineResponse, p: Palette, events: TlEvent[] = buildEvents(tl)) {
  const end = Math.max(tl.last_checkpoint_t_s ?? 0, ...events.map((e) => e.t), 1);
  const tol = end / 140;
  const lane = (name: Lane, filter?: (e: TlEvent) => boolean): Datum[] =>
    events.filter((e) => e.lane === name && (!filter || filter(e))).map((ev) => ({ value: [ev.t, name], link: ev.link, ev }));
  const scatter = (name: string, data: Datum[], symbol: string, size: number, color: string, extra: Record<string, unknown> = {}) => ({
    name,
    type: "scatter",
    xAxisIndex: 1,
    yAxisIndex: 2,
    data: data.map((d) => ({ ...d, itemStyle: { color: toneColor(p, d.ev.tone) === p.neutral ? color : toneColor(p, d.ev.tone) } })),
    symbol,
    symbolSize: size,
    itemStyle: { color },
    emphasis: { scale: 1.6 },
    cursor: "pointer",
    ...extra,
  });

  // Alternating stage bands (light) across both plots.
  const stageTimes = tl.stages.map((s) => s.t_s).filter((t): t is number => t != null);
  const bands = stageTimes.map((t0, i) => [{ xAxis: t0 }, { xAxis: stageTimes[i + 1] ?? end }]).filter((_, i) => i % 2 === 1);
  const stageMarkLine = {
    silent: true,
    symbol: "none",
    label: { show: false },
    lineStyle: { color: p.grid, type: "dashed", width: 1 },
    data: stageTimes.map((t) => ({ xAxis: t })),
  };
  const bandArea = { silent: true, itemStyle: { color: p.surface2, opacity: 0.55 }, data: bands };

  const series = tl.series.filter((s) => s.t_s != null);
  const axis = (gridIndex: number) => ({
    type: "value" as const,
    gridIndex,
    min: 0,
    max: end * 1.01,
    axisLabel: { color: p.muted, formatter: (v: number) => formatClock(v), hideOverlap: true },
    axisLine: { lineStyle: { color: p.grid } },
    splitLine: { show: gridIndex === 0, lineStyle: { color: p.grid } },
    axisPointer: { show: true, lineStyle: { color: p.muted, type: "dashed" }, label: { show: gridIndex === 1, formatter: (o: { value: number | string }) => formatClock(Number(o.value)), backgroundColor: p.neutral } },
  });

  return {
    animation: false,
    textStyle: { color: p.muted },
    legend: { top: 0, left: 0, textStyle: { color: p.text }, itemWidth: 14, itemHeight: 10, inactiveColor: p.grid, type: "scroll" },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: p.surface,
      borderColor: p.border,
      textStyle: { color: p.text, fontSize: 12 },
      extraCssText: "max-width:460px;white-space:normal;word-break:break-word;",
      // Every data-derived string goes through escapeHtml: tooltips are HTML (UI-5).
      formatter: (params: unknown) => {
        const arr = Array.isArray(params) ? params : [params];
        const x = Number((arr[0] as { axisValue?: number } | undefined)?.axisValue);
        if (!Number.isFinite(x)) return "";
        return tooltipLines(tl, events, x, tol).map(escapeHtml).join("<br/>");
      },
    },
    toolbox: {
      right: 8,
      top: 0,
      itemSize: 14,
      iconStyle: { borderColor: p.muted },
      feature: { dataZoom: { yAxisIndex: "none", title: { zoom: "Zoom to a time range (drag)", back: "Undo zoom" } }, restore: { title: "Reset" } },
    },
    grid: [
      { left: 64, right: 56, top: 62, height: 150 },
      { left: 64, right: 56, top: 238, height: 200 },
    ],
    xAxis: [axis(0), axis(1)],
    yAxis: [
      { type: "value", gridIndex: 0, name: "est. USD", nameTextStyle: { color: p.muted }, axisLabel: { color: p.muted, formatter: (v: number) => `$${v}` }, splitLine: { lineStyle: { color: p.grid } } },
      { type: "value", gridIndex: 0, name: "context", min: 0, max: 1, nameTextStyle: { color: p.muted }, axisLabel: { color: p.muted, formatter: (v: number) => `${Math.round(v * 100)}%` }, splitLine: { show: false } },
      { type: "category", gridIndex: 1, data: [...LANES], inverse: true, axisLabel: { color: p.text, fontSize: 12 }, axisTick: { show: false }, axisLine: { show: false }, splitLine: { show: true, lineStyle: { color: p.grid } } },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1], filterMode: "none" },
      { type: "slider", xAxisIndex: [0, 1], height: 22, bottom: 8, filterMode: "none", borderColor: p.border, textStyle: { color: p.muted }, labelFormatter: (v: number) => formatClock(v) },
    ],
    series: [
      {
        name: "Cumulative cost",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: series.map((s) => [s.t_s, s.cum_cost_usd]),
        symbolSize: 6,
        lineStyle: { width: 2, color: p.series[0] },
        itemStyle: { color: p.series[0] },
        markLine: stageMarkLine,
        markArea: bandArea,
      },
      {
        name: "Context fill (max)",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 1,
        data: series.map((s) => [s.t_s, s.context_fill_max]),
        symbolSize: 5,
        lineStyle: { width: 2, color: p.series[1], type: "solid" },
        itemStyle: { color: p.series[1] },
      },
      scatter("Checkpoints", lane("Checkpoints"), "diamond", 13, p.info),
      scatter("Stages", lane("Stages"), "rect", 10, p.neutral, { markLine: stageMarkLine, markArea: bandArea }),
      scatter("Compactions", lane("Compactions"), "roundRect", 13, p.info),
      scatter("Hazards", lane("Hazards"), "triangle", 15, p.bad),
      scatter("Behaviour", lane("Behaviour"), "circle", 8, p.warn),
      scatter("Guardrail", lane("Guardrail"), "pin", 14, p.warn),
    ],
  };
}

export function clickLink(data: unknown): string | null {
  if (data && typeof data === "object" && "link" in data) {
    const l = (data as { link: unknown }).link;
    return typeof l === "string" ? l : null;
  }
  return null;
}
