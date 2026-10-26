import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { initToken } from "../../api";
import { mockFetch, resetAuth } from "../../test/helpers";
import { FeedCard } from "./FeedCard";
import { buildRows } from "./feedStore";
import { LiveView } from "./LiveView";
import { HighlightedEvidence, SafetyPanelView } from "./SafetyPanel";
import type { DisplayEvent, SafetyData } from "./types";

import canAContext from "../../test/fixtures/feed_canA_context.json";
import canATail from "../../test/fixtures/feed_canA_tail.json";
import feedEvent from "../../test/fixtures/feed_event.json";
import haikuStart from "../../test/fixtures/feed_haiku_start.json";
import haikuTail from "../../test/fixtures/feed_haiku_tail.json";
import liveCanA from "../../test/fixtures/live_canA.json";
import liveHaiku from "../../test/fixtures/live_haiku.json";
import rules from "../../test/fixtures/rules.json";
import safetyCanA from "../../test/fixtures/safety_canA.json";
import safetyCanB from "../../test/fixtures/safety_canB.json";
import safetyHaiku from "../../test/fixtures/safety_haiku.json";

vi.mock("../../components/chart/LazyChart", () => ({
  LazyChart: ({ label }: { label: string }) => <div data-testid="chart" role="img" aria-label={label} />,
}));

const HOSTILE = "<img src=x onerror=alert(1)>";
const BIDI = "evil‮fdp.exe";
const SSE_FORGE = "x\n\nevent: run.ended\ndata: {}\n\n";
const HAIKU = "minidb-v3-pilot-haiku-A-r00-f47fe80e";
const CAN_A = "canary-forbidden-A-r00-fc5ddbfb";

beforeEach(() => {
  resetAuth();
  initToken();
});

function card(ev: DisplayEvent, result?: DisplayEvent, expanded = false) {
  return render(
    <MemoryRouter>
      <FeedCard runId="r1" row={{ key: ev.id, ev, result }} expanded={expanded} onToggle={() => {}} query="" />
    </MemoryRouter>,
  );
}
const evs = (a: unknown) => a as DisplayEvent[];
const find = (list: DisplayEvent[], pred: (e: DisplayEvent) => boolean) => {
  const e = list.find(pred);
  if (!e) throw new Error("fixture event missing");
  return e;
};
const all = [...evs(haikuStart.events), ...evs(haikuTail.events), ...evs(canATail.events)];

describe("feed cards from real events", () => {
  it.each([
    ["assistant_text", "Agent", /check the ops inbox/],
    ["checkpoint", null, /k=1/],
    ["stage", "Stage 0 delivered", /stage 0/],
    ["turn", "Turn started", /start/],
    ["state", null, /PENDING/],
    ["counterpart", "Embedding service mode", /embed\.mode/],
    ["test_run", "Agent ran tests", /70 passed/],
    ["guardrail", null, /other-outside/],
    ["kill", null, /rm-rf-root/],
    ["scorer", null, /k=/],
    ["session", "Session started", null],
    ["run", "Run clock started", null],
  ])("renders a %s card", (kind, title, chip) => {
    const ev = find(all, (e) => e.kind === kind);
    card(ev);
    const el = screen.getByTestId(`card-${kind}`);
    expect(el).toBeInTheDocument();
    if (title) expect(within(el).getByText(title)).toBeInTheDocument();
    if (chip) expect(el.textContent).toMatch(chip);
    expect(el.className).toContain(`k-${kind}`);
  });

  it("pairs a tool call with its result and shows ok", () => {
    const rows = buildRows(evs(haikuStart.events), { hidden: new Set(), minSeverity: "all", search: "" });
    const row = rows.find((r) => r.result)!;
    card(row.ev, row.result);
    expect(screen.getByTestId("card-tool_call").textContent).toMatch(/ok|error/);
  });

  it("a kill card is styled as a kill and the folded row shows its count", () => {
    card(find(all, (e) => e.kind === "kill"));
    expect(screen.getByTestId("card-kill").className).toContain("fc-sev-kill");
    const fold = find(all, (e) => e.kind === "folded");
    card(fold);
    expect(screen.getByTestId("card-folded").textContent).toMatch(/Telemetry silent/);
    expect(screen.getByTestId("card-folded").textContent).toMatch(/1 pause/);
  });

  it("falls back to a generic card for an unknown type and shows JSON on expand", () => {
    const ev = { ...all[0], id: "x:1", kind: "future_kind", type: "future.thing", title: "Future thing", summary: "", payload_preview: { a: 1 } };
    card(ev, undefined, true);
    expect(screen.getByTestId("card-future_kind").textContent).toMatch(/future\.thing/);
    expect(screen.getByLabelText("Event payload (text)").textContent).toContain('"a": 1');
  });

  it("expanding a truncated event fetches the full version", async () => {
    const m = mockFetch({ "/runs/r1/feed/event?ref=agent_stream%3A6111": feedEvent });
    const ev = { ...find(all, (e) => e.kind === "assistant_text"), truncated: true };
    card({ ...ev, cursor: "agent_stream:6111" }, undefined, true);
    await waitFor(() => expect(m.calls.some((c) => c.path.includes("feed/event?ref="))).toBe(true));
    expect(screen.getByRole("link", { name: /Open in transcript/ })).toHaveAttribute("href", "/runs/r1?tab=transcript&cursor=agent_stream%3A6111");
  });

  it("renders hostile strings as text only", () => {
    const ev = { ...all[0], id: "h:1", kind: "assistant_text", type: "assistant.text", title: HOSTILE, summary: BIDI, payload_preview: { text: `${HOSTILE}\u001b[31m${SSE_FORGE}` } };
    const { container } = card(ev, undefined, true);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain(HOSTILE);
    expect(screen.getByTestId("fulltext").textContent).toContain("event: run.ended");
    expect(screen.queryByText(/run ended/i)).toBeNull();
  });
});

describe("safety panel states", () => {
  const view = (data: unknown) =>
    render(
      <MemoryRouter>
        <SafetyPanelView runId="r1" data={data as SafetyData} live={false} />
      </MemoryRouter>,
    );

  it("killed (haiku pilot): banner with rule, delay and budget; groups with counts", () => {
    view(safetyHaiku);
    expect(document.querySelector(".sl")?.getAttribute("data-status")).toBe("killed");
    const kb = screen.getByTestId("kill-banner");
    expect(kb.textContent).toMatch(/KILL SWITCH FIRED/);
    expect(kb.textContent).toMatch(/budget/);
    expect(kb.textContent).toMatch(/27 ms/);
    expect(kb.textContent).toMatch(/\$15\.00 of \$15\.00/);
    expect(document.querySelector(".sl-sub")?.textContent).toMatch(/3 violations · 28 warnings/);
    // the violating groups are open by default, benign warning groups are collapsed
    const toggles = screen.getAllByRole("button", { expanded: false }).filter((b) => b.className === "gr-toggle");
    expect(toggles.map((b) => b.textContent).join(" ")).toMatch(/other-outside/);
    expect(screen.getAllByText("protected-path", { selector: ".gr-rule" })[0].closest("button")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("group", { name: "Group incidents" })).toBeInTheDocument();
    expect(screen.getByText(/Telemetry silent ~60 s x 106/)).toBeInTheDocument();
    expect(screen.getByText(/Scorer signals/)).toBeInTheDocument();
  });

  it("canary kills show the rule and the highlighted evidence", () => {
    view(safetyCanA);
    expect(screen.getByTestId("kill-banner").textContent).toMatch(/rm-rf-root/);
    const marks = within(screen.getByTestId("kill-banner")).getAllByText("rm -rf /", { selector: "mark" });
    expect(marks).toHaveLength(1);
    view(safetyCanB);
    expect(screen.getAllByTestId("kill-banner").at(-1)!.textContent).toMatch(/harness-access/);
  });

  it.each([
    ["clear", { status: "clear", counts: { incidents: 0, violations: 0, warnings: 0, kills: 0 }, kill: null, incidents: [], groups: [], incidents_total: 0 }, /No guardrail rule has fired/],
    ["warnings", { status: "warnings", kill: null, counts: { incidents: 1, violations: 0, warnings: 1, kills: 0 } }, /1 warning/],
    ["violations", { status: "violations", kill: null, counts: { incidents: 3, violations: 3, warnings: 0, kills: 0 } }, /3 violations/],
  ])("status light: %s", (status, patch, text) => {
    view({ ...(safetyHaiku as object), ...(patch as object) });
    expect(document.querySelector(".sl")?.getAttribute("data-status")).toBe(status);
    expect(screen.queryByTestId("kill-banner")).toBeNull();
    expect(document.body.textContent).toMatch(text);
  });

  it("incident card: evidence highlight by code point, explanation, action, context link", async () => {
    view(safetyCanA);
    await userEvent.click(screen.getByRole("button", { name: /Newest first/ }));
    const inc = screen.getAllByTestId("incident")[0];
    expect(inc.textContent).toMatch(/other-outside/);
    expect(inc.textContent).toMatch(/action: log/);
    expect(inc.textContent).toMatch(/workspace boundary/);
    expect(within(inc).getAllByText(/./, { selector: "mark" }).length).toBe(2);
    expect(within(inc).getByRole("link", { name: /Transcript/ })).toHaveAttribute("href", expect.stringContaining("tab=transcript&cursor=agent_stream%3A2087"));
  });

  it("show context loads the surrounding events and marks the trigger", async () => {
    const m = mockFetch({ [`/runs/r1/feed?ref_from=${encodeURIComponent("agent_stream:458")}&ref_to=${encodeURIComponent("agent_stream:2087")}`]: canAContext });
    view(safetyCanA);
    await userEvent.click(screen.getByRole("button", { name: /Newest first/ }));
    await userEvent.click(screen.getAllByRole("button", { name: /Show context/ })[0]);
    await screen.findByLabelText("Events around the incident");
    expect(m.calls).toHaveLength(1);
    expect(document.querySelector(".ctx-center")).not.toBeNull();
    expect(screen.getByText("trigger")).toBeInTheDocument();
  });

  it("hostile rule ids, evidence and explanations stay text; highlight ranges are clamped", () => {
    const bad = JSON.parse(JSON.stringify(safetyCanA)) as SafetyData;
    bad.incidents[0].evidence = `${HOSTILE} ${BIDI} \u{1F600}${SSE_FORGE}`;
    bad.incidents[0].evidence_highlight = [[0, 999], [3, 1], [-5, 2]];
    bad.incidents[0].rule_id = HOSTILE;
    bad.incidents[0].explanation = HOSTILE;
    bad.groups[0].rule_id = HOSTILE;
    bad.groups[0].incident_ids = [];
    const { container } = view(bad);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain(HOSTILE);
  });

  it("HighlightedEvidence slices by code point (astral characters)", () => {
    const { container } = render(<HighlightedEvidence text={"\u{1F600}ab\u{1F600}cd"} ranges={[[3, 5]]} />);
    expect(container.querySelector("mark")?.textContent).toBe("\u{1F600}c");
  });

  it("rule legend loads /api/rules", async () => {
    mockFetch({ "/rules": rules });
    view(safetyCanA);
    await userEvent.click(screen.getByRole("button", { name: /Rule legend/ }));
    expect(await screen.findByRole("dialog", { name: "Guardrail rules" })).toBeInTheDocument();
    expect(await screen.findByText("destructive-git")).toBeInTheDocument();
  });
});

describe("no notifications or sounds", () => {
  it("never touches the Notification API or audio", async () => {
    const N = vi.fn();
    vi.stubGlobal("Notification", N);
    const A = vi.fn();
    vi.stubGlobal("Audio", A);
    render(
      <MemoryRouter>
        <SafetyPanelView runId="r1" data={safetyHaiku as unknown as SafetyData} live />
      </MemoryRouter>,
    );
    expect(N).not.toHaveBeenCalled();
    expect(A).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("the source of the live view has no Notification, Audio or AudioContext use", () => {
    const files = import.meta.glob("./*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    for (const [name, src] of Object.entries(files)) {
      if (name.includes(".test.")) continue;
      expect(src, name).not.toMatch(/new Notification|Notification\.requestPermission|new Audio\(|AudioContext|\.play\(\)/);
    }
  });
});

describe("LiveView replay of a finished run", () => {
  it("loads from the start, draws cards, the safety panel and the status strip", async () => {
    const m = mockFetch({
      [`/runs/${HAIKU}/live`]: liveHaiku,
      [`/runs/${HAIKU}/feed?from=start&limit=400&level=info`]: { ...haikuStart, at_end: true, next_cursor: "v1:x=1" },
      [`/runs/${HAIKU}/safety?limit=200`]: safetyHaiku,
    });
    render(
      <MemoryRouter initialEntries={[`/runs/${HAIKU}/live`]}>
        <Routes>
          <Route path="/runs/:runId/live" element={<LiveView />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { level: 1, name: new RegExp(`Replay ${HAIKU}`) })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByTestId(/^card-/).length).toBeGreaterThan(5));
    expect(await screen.findByTestId("kill-banner")).toBeInTheDocument();
    expect(screen.getByText("14 of 14 scored")).toBeInTheDocument();
    expect(screen.getAllByRole("meter").length).toBe(3); // overview only: the panel's own meter is hidden here
    expect(screen.getAllByTestId("chart").length).toBe(2);
    expect(m.calls.some((c) => c.path.includes("/stream"))).toBe(false); // finished run: no stream
    // source chips and the search box work
    await userEvent.click(screen.getByRole("button", { name: /Guardrails/ }));
    expect(screen.getByRole("button", { name: /Guardrails/ })).toHaveAttribute("aria-pressed", "false");
    await userEvent.type(screen.getByRole("searchbox", { name: "Search the feed" }), "zzzzqq");
    expect(await screen.findByText("No events match the filters.")).toBeInTheDocument();
  });

  it("a live canary-style snapshot decides live mode and opens the stream with the token header", async () => {
    const liveSnap = { ...liveCanA, live: true, ended: false, state: "RUNNING" };
    const m = mockFetch({ [`/runs/${CAN_A}/live`]: liveSnap, [`/runs/${CAN_A}/safety?limit=200`]: safetyCanA });
    // the stream stub answers 200 with an empty, closed body: the client then reconnects; we only check the first call
    const fetchSpy = vi.mocked(globalThis.fetch);
    const base = fetchSpy.getMockImplementation()!;
    const streamCalls: { url: string; headers: Record<string, string> }[] = [];
    fetchSpy.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/stream")) {
        streamCalls.push({ url, headers: init?.headers as Record<string, string> });
        return new Response(new ReadableStream({ start() { /* stays open */ } }), { status: 200 });
      }
      return base(input, init);
    });
    const { unmount } = render(
      <MemoryRouter initialEntries={[`/runs/${CAN_A}/live`]}>
        <Routes>
          <Route path="/runs/:runId/live" element={<LiveView />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(streamCalls).toHaveLength(1));
    expect(streamCalls[0].headers["X-LRAE-Token"]).toBe("test-token");
    expect(streamCalls[0].url).toMatch(/from=tail&backlog=300&level=info/);
    expect(screen.getByRole("heading", { level: 1, name: /^Live/ })).toBeInTheDocument();
    unmount();
    expect(m.calls.length).toBeGreaterThan(0);
  });
});
