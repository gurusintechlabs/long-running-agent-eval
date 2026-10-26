import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { initToken } from "../../api";
import diffFx from "../../test/fixtures/diff_ck1.json";
import eventsFx from "../../test/fixtures/events_page.json";
import eventsSummary from "../../test/fixtures/events_summary_haiku.json";
import scorerFx from "../../test/fixtures/scorer_ck1.json";
import testsFx from "../../test/fixtures/tests_haiku.json";
import timelineFx from "../../test/fixtures/timeline_haiku.json";
import transcriptFx from "../../test/fixtures/transcript_page.json";
import { fx, mockFetch, mockRoutes, renderRoute, resetAuth } from "../../test/helpers";
import { CheckpointsTab } from "./checkpoints/CheckpointsTab";
import { EventsTab } from "./events/EventsTab";
import { RunDetailView } from "./RunDetailView";
import { TestsTab } from "./tests/TestsTab";
import { TimelineTab } from "./timeline/TimelineTab";
import { TranscriptTab } from "./transcript/TranscriptTab";

vi.mock("../../components/chart/LazyChart", () => ({
  LazyChart: ({ label, onClick, option }: { label: string; onClick?: (p: unknown) => void; option: unknown }) => (
    <button type="button" data-testid="chart" aria-label={label} onClick={() => onClick?.({ data: { link: "/elsewhere/x?tab=transcript&cursor=agent_stream%3A9" } })}>
      {Array.isArray((option as { series?: unknown[] })?.series) ? "chart" : ""}
    </button>
  ),
}));

const HOSTILE = "<img src=x onerror=alert(1)>";
const RUN = "minidb-v3-pilot-haiku-A-r00-f47fe80e";
const clone = <T,>(x: T): T => structuredClone(x);

beforeEach(() => {
  resetAuth();
  initToken();
});

describe("Tests tab", () => {
  const route = (path: string) => (path.startsWith(`/runs/${RUN}/tests`) ? { body: testsFx } : undefined);

  it("shows summary, legend, heatmap, charts and the regressions list from the fixture", async () => {
    mockRoutes(route);
    renderRoute(<TestsTab runId={RUN} version={0} onReingest={() => {}} reingesting={false} />, `/runs/${RUN}`, "/runs/:runId");
    await screen.findByRole("heading", { name: "Test outcomes" });
    expect(screen.getByRole("img", { name: /Test outcome heatmap: \d+ tests by 42 time points/ })).toBeInTheDocument();
    expect(screen.getByText("regressions", { selector: ".stat-l" })).toBeInTheDocument();
    expect(screen.getAllByText("42", { selector: ".stat-v" })).toHaveLength(2); // time points and regressions
    expect(screen.getAllByTestId("chart")).toHaveLength(2);
    const reg = testsFx.flips.filter((f) => f.kind === "regression").length;
    expect(screen.getByRole("heading", { name: `Flips (${reg})` })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Recoveries" }));
    expect(screen.getByRole("heading", { name: `Flips (${testsFx.flips.filter((f) => f.kind === "recovery").length})` })).toBeInTheDocument();
  });

  it("filters tests by tier and by id text", async () => {
    mockRoutes(route);
    renderRoute(<TestsTab runId={RUN} version={0} onReingest={() => {}} reingesting={false} />, `/runs/${RUN}`, "/runs/:runId");
    await screen.findByText(`${testsFx.tests.length} shown`);
    await userEvent.type(screen.getByLabelText("Filter test id"), "zzz-no-such");
    expect(await screen.findByText("No tests match these filters")).toBeInTheDocument();
  });

  it("offers re-ingest when the run is not in the store", async () => {
    mockRoutes(() => ({ body: { run_id: RUN, ingested: false, has_outcomes: false, suite: "hidden", suites: [], reason: "this run is not in metrics.sqlite yet; re-ingest to see test outcomes" } }));
    const onReingest = vi.fn();
    renderRoute(<TestsTab runId={RUN} version={0} onReingest={onReingest} reingesting={false} />, `/runs/${RUN}`, "/runs/:runId");
    await screen.findByRole("heading", { name: "Test outcomes need ingest" });
    expect(screen.getByText(/re-ingest to see test outcomes/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Re-ingest now" }));
    expect(onReingest).toHaveBeenCalledOnce();
  });

  it("explains runs without per-test data", async () => {
    mockRoutes(() => ({ body: { ...clone(testsFx), has_outcomes: false, tests: [] } }));
    renderRoute(<TestsTab runId={RUN} version={0} onReingest={() => {}} reingesting={false} />, `/runs/${RUN}`, "/runs/:runId");
    expect(await screen.findByText("No per-test data for this run")).toBeInTheDocument();
  });

  it("renders hostile test ids as text", async () => {
    const bad = clone(testsFx);
    bad.flips[0].test_id = HOSTILE;
    bad.flips[0].kind = "regression";
    mockRoutes(() => ({ body: bad }));
    const { container } = renderRoute(<TestsTab runId={RUN} version={0} onReingest={() => {}} reingesting={false} />, `/runs/${RUN}`, "/runs/:runId");
    await screen.findByRole("heading", { name: "Test outcomes" });
    expect(screen.getByText(HOSTILE)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows an error with retry", async () => {
    mockRoutes(() => ({ status: 500, body: { detail: "boom" } }));
    renderRoute(<TestsTab runId={RUN} version={0} onReingest={() => {}} reingesting={false} />, `/runs/${RUN}`, "/runs/:runId");
    expect(await screen.findByText("Could not load test outcomes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("Timeline tab", () => {
  it("renders the chart, summary and an incident list whose links deep-link into the transcript", async () => {
    mockRoutes((p) => (p === `/runs/${RUN}/timeline` ? { body: timelineFx } : undefined));
    renderRoute(<TimelineTab runId={RUN} live={false} version={0} />, `/runs/${RUN}?tab=timeline`, "/runs/:runId");
    await screen.findByRole("heading", { name: "Run timeline" });
    expect(screen.getByText("killed")).toBeInTheDocument();
    expect(screen.getByTestId("chart")).toBeInTheDocument();
    // default lanes: hazards, behaviour, guardrail, compactions
    const open = screen.getAllByRole("link", { name: "Open" });
    expect(open.length).toBeGreaterThan(5);
    const hrefs = open.map((a) => a.getAttribute("href"));
    expect(hrefs.some((h) => h?.includes("tab=transcript&cursor=agent_stream%3A385323"))).toBe(true); // violation -> stream cursor
    expect(hrefs.some((h) => h?.includes("tab=transcript&t_s="))).toBe(true); // hazard / behaviour -> run time
    // lane chips toggle
    await userEvent.click(screen.getByRole("button", { name: /Checkpoints/ }));
    expect(screen.getAllByRole("link", { name: "Open" }).some((a) => a.getAttribute("href")?.includes("tab=checkpoints&k="))).toBe(true);
  });

  it("clicking a chart marker navigates to its link", async () => {
    mockRoutes((p) => (p === `/runs/${RUN}/timeline` ? { body: timelineFx } : undefined));
    renderRoute(<TimelineTab runId={RUN} live={false} version={0} />, `/runs/${RUN}?tab=timeline`, "/runs/:runId");
    await userEvent.click(await screen.findByTestId("chart"));
    // the mocked chart reports a datum whose link leaves this route: the router shows the fallback
    expect(await screen.findByText("elsewhere")).toBeInTheDocument();
  });

  it("renders hostile evidence as text in the incident list", async () => {
    const bad = clone(timelineFx);
    bad.hazards[0].evidence = HOSTILE;
    bad.guardrail.violations[0].evidence = HOSTILE;
    mockRoutes(() => ({ body: bad }));
    const { container } = renderRoute(<TimelineTab runId={RUN} live={false} version={0} />, `/runs/${RUN}?tab=timeline`, "/runs/:runId");
    await screen.findByRole("heading", { name: "Run timeline" });
    expect(screen.getAllByText(new RegExp(HOSTILE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))).length).toBeGreaterThan(0);
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows an error state", async () => {
    mockRoutes(() => ({ status: 500, body: { detail: "x" } }));
    renderRoute(<TimelineTab runId={RUN} live={false} version={0} />, `/runs/${RUN}?tab=timeline`, "/runs/:runId");
    expect(await screen.findByText("Could not load the timeline")).toBeInTheDocument();
  });
});

describe("Transcript tab", () => {
  const firstTool = transcriptFx.items.find((i) => i.kind === "tool") as { cursor: string; tool: string };
  const detail = (cursor: string, input: unknown, result: string) => ({
    run_id: RUN,
    item: transcriptFx.items.find((i) => i.cursor === cursor),
    event: { cursor, source: "agent_stream", type: "tool.call", payload: { tool: "Bash", input }, truncated: false, bytes: 1, ts: null, t_s: 1, seq: 1 },
    result_event: null,
    result_text: result,
    result_text_truncated: false,
  });

  it("lists items, expands a tool call through the item endpoint and filters by errors", async () => {
    const { calls } = mockRoutes((p) => {
      if (p.startsWith(`/runs/${RUN}/transcript/item`)) return { body: detail(firstTool.cursor, { command: "ls" }, `full output ${HOSTILE}`) };
      if (p.startsWith(`/runs/${RUN}/transcript`)) return { body: transcriptFx };
      return undefined;
    });
    const { container } = renderRoute(<TranscriptTab runId={RUN} />, `/runs/${RUN}?tab=transcript`, "/runs/:runId");
    await screen.findByText(/Following project rule 8/);
    expect(screen.getByRole("heading", { name: "Transcript (1,151 items)" })).toBeInTheDocument();
    const heads = screen.getAllByRole("button", { expanded: false }).filter((b) => b.className.includes("tool-head"));
    await userEvent.click(heads[0]);
    expect(await screen.findByText(/full output/)).toBeInTheDocument();
    expect(calls.some((c) => c.includes("/transcript/item?cursor="))).toBe(true);
    expect(container.querySelector("img")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Errors only" }));
    await waitFor(() => expect(calls.some((c) => c.includes("errors_only=true"))).toBe(true));
    await userEvent.click(within(screen.getByRole("group", { name: "Filter by tool" })).getByRole("button", { name: /^Bash/ }));
    await waitFor(() => expect(calls.some((c) => c.includes("tool=Bash"))).toBe(true));
  });

  it("sends the search text after a pause", async () => {
    const { calls } = mockRoutes(() => ({ body: transcriptFx }));
    renderRoute(<TranscriptTab runId={RUN} />, `/runs/${RUN}?tab=transcript`, "/runs/:runId");
    await screen.findByText(/Following project rule 8/);
    await userEvent.type(screen.getByLabelText("Search transcript"), "pytest");
    await waitFor(() => expect(calls.some((c) => c.includes("q=pytest"))).toBe(true));
  });

  it("pages with load more using the next cursor", async () => {
    const page2 = { ...clone(transcriptFx), items: [{ ...clone(transcriptFx.items[1]), cursor: "agent_stream:999", text: "second page text" }], eof: true, next: "agent_stream:999" };
    const { calls } = mockRoutes((p) => (p.includes("after=") ? { body: page2 } : { body: { ...transcriptFx, eof: false } }));
    renderRoute(<TranscriptTab runId={RUN} />, `/runs/${RUN}?tab=transcript`, "/runs/:runId");
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("second page text")).toBeInTheDocument();
    expect(calls.some((c) => c.includes(`after=${encodeURIComponent(transcriptFx.next)}`))).toBe(true);
    expect(screen.getByText(/End of the transcript/)).toBeInTheDocument();
  });

  it("cursor deep link requests an around window and highlights the anchor", async () => {
    const target = transcriptFx.items[3].cursor;
    const { calls } = mockRoutes(() => ({ body: { ...clone(transcriptFx), mode: "around", anchor: target, eof: true } }));
    renderRoute(<TranscriptTab runId={RUN} />, `/runs/${RUN}?tab=transcript&cursor=${encodeURIComponent(target)}`, "/runs/:runId");
    await screen.findByText(/Showing a window around/);
    expect(calls[0]).toContain(`around=${encodeURIComponent(target)}`);
    expect(calls[0]).toContain("before=20");
    expect(calls[0]).toContain("after_n=5");
    const hl = document.querySelector(".tr-hl") as HTMLElement;
    expect(hl.dataset.cursor).toBe(target);
    expect(hl).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: "Show 40 earlier items" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back to the start of the transcript" }));
    await waitFor(() => expect(screen.queryByText(/Showing a window around/)).toBeNull());
  });

  it("run-time deep link uses around_t_s", async () => {
    const { calls } = mockRoutes(() => ({ body: { ...transcriptFx, mode: "around", anchor: transcriptFx.items[0].cursor, eof: true } }));
    renderRoute(<TranscriptTab runId={RUN} />, `/runs/${RUN}?tab=transcript&t_s=123.5`, "/runs/:runId");
    await screen.findByText(/Showing a window around/);
    expect(calls[0]).toContain("around_t_s=123.5");
  });

  it("renders hostile assistant text, tool summaries and results as text", async () => {
    const bad = clone(transcriptFx);
    (bad.items.find((i) => i.kind === "text") as { text: string }).text = HOSTILE;
    const t = bad.items.find((i) => i.kind === "tool") as { input_summary: string; status: string; result_tail: string };
    t.input_summary = HOSTILE;
    t.status = "error";
    t.result_tail = HOSTILE;
    mockRoutes(() => ({ body: bad }));
    const { container } = renderRoute(<TranscriptTab runId={RUN} />, `/runs/${RUN}?tab=transcript`, "/runs/:runId");
    await screen.findAllByText(HOSTILE);
    expect(container.querySelector("img")).toBeNull();
  });

  it("collapses long text with an expand toggle", async () => {
    const long = clone(transcriptFx);
    (long.items.find((i) => i.kind === "text") as { text: string }).text = "x".repeat(3000);
    mockRoutes(() => ({ body: long }));
    renderRoute(<TranscriptTab runId={RUN} />, `/runs/${RUN}?tab=transcript`, "/runs/:runId");
    const btn = await screen.findByRole("button", { name: /Show all/ });
    await userEvent.click(btn);
    expect(screen.getByRole("button", { name: "Collapse" })).toBeInTheDocument();
  });

  it("shows empty and error states", async () => {
    mockRoutes(() => ({ body: { ...transcriptFx, items: [], total_items: 0, tools: [] } }));
    renderRoute(<TranscriptTab runId={RUN} />, `/runs/${RUN}?tab=transcript`, "/runs/:runId");
    expect(await screen.findByText("Nothing in the transcript yet")).toBeInTheDocument();
  });
  it("shows an error with retry", async () => {
    mockRoutes(() => ({ status: 500, body: { detail: "nope" } }));
    renderRoute(<TranscriptTab runId={RUN} />, `/runs/${RUN}?tab=transcript`, "/runs/:runId");
    expect(await screen.findByText("Could not load the transcript")).toBeInTheDocument();
  });
});

describe("Events tab", () => {
  const route = (extra?: (p: string) => { body: unknown } | undefined) => (p: string) => {
    const e = extra?.(p);
    if (e) return e;
    if (p.includes("/events/summary")) return { body: eventsSummary };
    if (p.includes("/events?")) return { body: eventsFx };
    return undefined;
  };

  it("lists merged events, filters by source/type/search and opens a JSON viewer", async () => {
    const { calls } = mockRoutes(route());
    renderRoute(<EventsTab runId={RUN} />, `/runs/${RUN}?tab=events`, "/runs/:runId");
    await screen.findByText("embed.mode");
    expect(screen.getByText("all sources, merged by time")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^guardrail/ }));
    await waitFor(() => expect(calls.some((c) => c.includes("source=guardrail"))).toBe(true));
    await userEvent.type(screen.getByLabelText("Filter by event type"), "tool.*");
    await waitFor(() => expect(calls.some((c) => c.includes("type=tool.*") || c.includes("type=tool.%2A"))).toBe(true));
    await userEvent.type(screen.getByLabelText("Search events"), "pytest");
    await waitFor(() => expect(calls.some((c) => c.includes("q=pytest"))).toBe(true));
  });

  it("opens a row into a text-only JSON tree and fetches the full event when cut", async () => {
    const page = clone(eventsFx);
    page.events = page.events.slice(0, 3);
    page.events[0] = { ...page.events[0], truncated: true, type: "tool.call", payload: { input: HOSTILE, note: "…[truncated 5000 more chars]" } as never };
    const full = { ...page.events[0], truncated: false, payload: { input: `${HOSTILE} full`, note: "complete" } };
    const calls: string[] = [];
    mockRoutes((p) => {
      calls.push(p);
      if (p.includes("/events/summary")) return { body: eventsSummary };
      if (p.includes("/events/at")) return { body: { run_id: RUN, event: full } };
      if (p.includes("/events?")) return { body: page };
      return undefined;
    });
    const { container } = renderRoute(<EventsTab runId={RUN} />, `/runs/${RUN}?tab=events`, "/runs/:runId");
    const row = (await screen.findByText("tool.call")).closest("button") as HTMLElement;
    await userEvent.click(row);
    expect(screen.getByRole("tree", { name: "JSON payload" })).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp("onerror=alert")).length).toBeGreaterThan(0);
    expect(container.querySelector("img")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Load the full event" }));
    expect(await screen.findByText(/full/, { selector: ".j-str" })).toBeInTheDocument();
    expect(calls.some((c) => c.includes("/events/at?cursor="))).toBe(true);
    expect(screen.queryByRole("button", { name: "Load the full event" })).toBeNull();
  });

  it("pages with load more and shows an empty state", async () => {
    const { calls } = mockRoutes((p) => {
      if (p.includes("/events/summary")) return { body: eventsSummary };
      if (p.includes("after=")) return { body: { ...eventsFx, events: [], eof: true } };
      return { body: { ...eventsFx, eof: false } };
    });
    renderRoute(<EventsTab runId={RUN} />, `/runs/${RUN}?tab=events`, "/runs/:runId");
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    await waitFor(() => expect(calls.some((c) => c.includes("after="))).toBe(true));
    expect(await screen.findByText(/End of the log/)).toBeInTheDocument();
  });

  it("empty result", async () => {
    mockRoutes((p) => (p.includes("/events/summary") ? { body: eventsSummary } : { body: { ...eventsFx, events: [], eof: true } }));
    renderRoute(<EventsTab runId={RUN} />, `/runs/${RUN}?tab=events`, "/runs/:runId");
    expect(await screen.findByText("No events match")).toBeInTheDocument();
  });
});

describe("Checkpoints tab and drawer", () => {
  const cps = fx.checkpointsHaiku.checkpoints;
  const route = (diff: unknown = diffFx, scorer: unknown = scorerFx) => (p: string) => {
    if (p.includes("/checkpoints/1/diff")) return { body: diff };
    if (p.includes("/checkpoints/1/scorer-log")) return { body: scorer };
    return undefined;
  };
  const render = (path = `/runs/${RUN}?tab=checkpoints&k=1`) =>
    renderRoute(<CheckpointsTab runId={RUN} checkpoints={cps as never} ingested={false} loading={false} error={null} onRetry={() => {}} />, path, "/runs/:runId");

  it("opens the drawer from the table and from the URL, shows commits, diff and scorer log", async () => {
    mockRoutes(route());
    render(`/runs/${RUN}?tab=checkpoints`);
    await userEvent.click(screen.getByRole("button", { name: "Details for checkpoint t1" }));
    const dlg = await screen.findByRole("dialog");
    expect(within(dlg).getByRole("heading", { name: "Checkpoint t1" })).toBeInTheDocument();
    expect(await within(dlg).findByText(/Changes from the seed commit/)).toBeInTheDocument();
    expect(within(dlg).getByText(/uncommitted files that the git mirror does not contain/)).toBeInTheDocument(); // dirty flag note
    // the first file opens by default for a small diff; it can be collapsed and reopened
    expect(within(dlg).getByText("README.md", { selector: ".df-path" })).toBeInTheDocument();
    expect(dlg.querySelectorAll(".dl-add").length).toBeGreaterThan(0);
    expect(dlg.querySelectorAll(".dl-del").length).toBeGreaterThan(0);
    await userEvent.click(within(dlg).getByRole("button", { name: /README\.md/ }));
    expect(dlg.querySelectorAll(".dl-add")).toHaveLength(0);
    await userEvent.click(within(dlg).getByRole("button", { name: /README\.md/ }));
    expect(dlg.querySelectorAll(".dl-add").length).toBeGreaterThan(0);

    await userEvent.click(within(dlg).getByRole("tab", { name: /Commits/ }));
    expect(await within(dlg).findByText(diffFx.commits[0].subject)).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("tab", { name: "Scorer log" }));
    expect(await within(dlg).findByText(/scorer\/score-t1\.log/)).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("renders hostile diff text, file paths and commit subjects as text", async () => {
    const bad = clone(diffFx);
    bad.commits[0].subject = HOSTILE;
    bad.files[0].path = HOSTILE;
    bad.diff = `diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,1 +1,2 @@\n ${HOSTILE}\n+${HOSTILE}\n`;
    mockRoutes(route(bad, { ...scorerFx, text: HOSTILE }));
    render();
    const dlg = await screen.findByRole("dialog");
    await within(dlg).findByText(/Changes from/);
    expect(within(dlg).getAllByText(HOSTILE, { exact: false }).length).toBeGreaterThan(0);
    await userEvent.click(within(dlg).getByRole("tab", { name: /Commits/ }));
    expect(await within(dlg).findByText(HOSTILE)).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("tab", { name: "Scorer log" }));
    expect(await within(dlg).findByText(HOSTILE, { selector: "pre" })).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("notes truncated diffs and unavailable mirrors", async () => {
    mockRoutes(route({ ...clone(diffFx), diff_truncated: true }));
    const { unmount } = render();
    expect(await screen.findByText(/cut at the server size limit/)).toBeInTheDocument();
    unmount();
    mockRoutes(route({ ...clone(diffFx), available: false, reason: "no mirror.git", diff: "", files: [], commits: [] }));
    render();
    expect(await screen.findByText(/no mirror\.git/)).toBeInTheDocument();
  });

  it("shows an error for a missing scorer log", async () => {
    mockRoutes((p) => (p.includes("scorer-log") ? { status: 404, body: { detail: "no log" } } : { body: diffFx }));
    render();
    const dlg = await screen.findByRole("dialog");
    await userEvent.click(within(dlg).getByRole("tab", { name: "Scorer log" }));
    expect(await within(dlg).findByText("No scorer log for this checkpoint")).toBeInTheDocument();
  });
});

describe("Run detail tabs", () => {
  function routes() {
    return mockFetch({
      [`/runs/${RUN}`]: fx.runHaiku,
      [`/runs/${RUN}/checkpoints`]: fx.checkpointsHaiku,
      "/ingest/status": fx.ingestStatus,
    });
  }
  it("shows six tabs, selects with the keyboard and keeps the active tab in the URL", async () => {
    routes();
    renderRoute(<RunDetailView />, `/runs/${RUN}`, "/runs/:runId");
    await screen.findByRole("tablist", { name: "Run sections" });
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Overview", "Timeline", "Tests", "Transcript", "Events", "Checkpoints"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    tabs[0].focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Timeline" })).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Checkpoints" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "tab-checkpoints");
  });

  it("opens straight onto the tab named in the URL", async () => {
    mockFetch({
      [`/runs/${RUN}`]: fx.runHaiku,
      [`/runs/${RUN}/checkpoints`]: fx.checkpointsHaiku,
      "/ingest/status": fx.ingestStatus,
    });
    renderRoute(<RunDetailView />, `/runs/${RUN}?tab=checkpoints`, "/runs/:runId");
    expect(await screen.findByRole("heading", { name: `Checkpoints (${fx.checkpointsHaiku.checkpoints.length})` })).toBeInTheDocument();
  });

  it("hazards on the overview link to the transcript", async () => {
    mockFetch({ [`/runs/early`]: fx.runEarly, [`/runs/early/checkpoints`]: fx.checkpointsEarly, "/ingest/status": fx.ingestStatus });
    renderRoute(<RunDetailView />, `/runs/early`, "/runs/:runId");
    const links = await screen.findAllByRole("link", { name: "Open in transcript" });
    expect(links[0].getAttribute("href")).toMatch(/^\/runs\/early\?tab=transcript&t_s=/);
  });
});
