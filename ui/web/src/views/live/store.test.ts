import { describe, expect, it } from "vitest";
import { applyEvents, buildRows, countBySource, emptyFeed, type FeedFilters } from "./feedStore";
import { applyBadge } from "./useTabBadge";
import type { DisplayEvent } from "./types";

import feedStart from "../../test/fixtures/feed_haiku_start.json";

let n = 0;
function mk(over: Partial<DisplayEvent> = {}): DisplayEvent {
  n++;
  return {
    id: `agent_stream:${n}`, cursor: `agent_stream:${n}`, ts: `2026-10-23T10:00:${String(n % 60).padStart(2, "0")}.000000Z`, t_s: n, source: "agent_stream",
    type: "tool.call", kind: "tool_call", title: "Edit", summary: "x", severity: "info", pair: null, payload_preview: {}, fold: null, ...over,
  };
}
const ALL: FeedFilters = { hidden: new Set(), minSeverity: "all", search: "" };

describe("feed reducer", () => {
  it("replaces a folded row by id, in place, without growing", () => {
    const fold = (pairs: number) => mk({ id: "fold:telemetry_stall", kind: "folded", type: "telemetry_silent", source: "guardrail", title: `Telemetry silent x ${pairs}`, fold: { group: "telemetry_stall", pairs, open: false } });
    let s = applyEvents(emptyFeed(), [mk({ ts: "2026-10-23T10:00:01Z" }), fold(1), mk({ ts: "2026-10-23T10:00:30Z" })]);
    expect(s.events).toHaveLength(3);
    s = applyEvents(s, [fold(2), mk({ ts: "2026-10-23T10:00:40Z" }), fold(3)]);
    expect(s.events).toHaveLength(4);
    const f = s.events.filter((e) => e.id === "fold:telemetry_stall");
    expect(f).toHaveLength(1);
    expect(f[0].fold?.pairs).toBe(3);
    expect(s.events[1].id).toBe("fold:telemetry_stall"); // kept where it first appeared
  });

  it("ignores duplicates after a reconnect and counts only new ids", () => {
    const a = mk();
    let s = applyEvents(emptyFeed(), [a]);
    s = applyEvents(s, [a, { ...a }]);
    expect(s.events).toHaveLength(1);
    expect(s.accepted).toBe(1);
  });

  it("slots a late line from another file by timestamp", () => {
    const e1 = mk({ ts: "2026-10-23T10:00:01Z" });
    const e3 = mk({ ts: "2026-10-23T10:00:03Z" });
    const late = mk({ ts: "2026-10-23T10:00:02Z", source: "guardrail" });
    const s = applyEvents(applyEvents(emptyFeed(), [e1, e3]), [late]);
    expect(s.events.map((e) => e.id)).toEqual([e1.id, late.id, e3.id]);
  });

  it("bounds the buffer: oldest events are dropped and their ids forgotten", () => {
    let s = emptyFeed();
    const first: DisplayEvent[] = [];
    for (let i = 0; i < 50; i++) {
      const batch = Array.from({ length: 100 }, () => mk({ ts: null }));
      if (i === 0) first.push(...batch);
      s = applyEvents(s, batch, 1000);
    }
    expect(s.events.length).toBe(1000);
    expect(s.dropped).toBe(4000);
    expect(s.ids.size).toBe(1000);
    expect(s.ids.has(first[0].id)).toBe(false);
    expect(s.events[999].id).toBe(`agent_stream:${n}`);
  });
});

describe("rows and filters", () => {
  const call = mk({ pair: "t1", title: "Bash", summary: "ls -la" });
  const res = mk({ pair: "t1", kind: "tool_result", type: "tool.result", title: "Bash ok", summary: "done", severity: "warning" });
  const lone = mk({ kind: "tool_result", pair: "gone", title: "Orphan result" });
  const guard = mk({ source: "guardrail", kind: "guardrail", severity: "violation", title: "rule x (violation, log)" });
  const evs = [call, res, lone, guard];

  it("merges a result into its call and lifts the row severity", () => {
    const rows = buildRows(evs, ALL);
    expect(rows).toHaveLength(3);
    expect(rows[0].result?.id).toBe(res.id);
    expect(buildRows(evs, { ...ALL, minSeverity: "warning" }).map((r) => r.ev.id)).toEqual([call.id, guard.id]);
    expect(buildRows(evs, { ...ALL, minSeverity: "violation" }).map((r) => r.ev.id)).toEqual([guard.id]);
  });

  it("filters by source chips and by search (title, summary and payload)", () => {
    expect(buildRows(evs, { ...ALL, hidden: new Set(["guardrail"]) }).map((r) => r.ev.id)).not.toContain(guard.id);
    expect(buildRows(evs, { ...ALL, search: "LS -LA" }).map((r) => r.ev.id)).toEqual([call.id]);
    const p = mk({ payload_preview: { text: "needle in payload" } });
    expect(buildRows([p], { ...ALL, search: "needle" })).toHaveLength(1);
    expect(countBySource(evs)).toEqual({ agent_stream: 3, guardrail: 1 });
  });

  it("a kill row stays visible even when its source is switched off", () => {
    const k = mk({ source: "guardrail", kind: "kill", severity: "kill" });
    expect(buildRows([k], { ...ALL, hidden: new Set(["guardrail"]) })).toHaveLength(1);
  });

  it("handles a real page of the haiku pilot", () => {
    const rows = buildRows(feedStart.events as unknown as DisplayEvent[], ALL);
    expect(rows.length).toBeLessThan(feedStart.events.length); // results merged into calls
    expect(rows.some((r) => r.result)).toBe(true);
  });
});

describe("tab badge title", () => {
  it("adds and removes the prefix idempotently", () => {
    expect(applyBadge("Live · LRAE", 3)).toBe("(3!) Live · LRAE");
    expect(applyBadge("(3!) Live · LRAE", 5)).toBe("(5!) Live · LRAE");
    expect(applyBadge("(5!) Live · LRAE", 0)).toBe("Live · LRAE");
  });
});
