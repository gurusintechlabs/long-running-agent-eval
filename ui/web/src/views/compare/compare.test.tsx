import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { initToken, type CompareResponse, type SurvivalResponse } from "../../api";
import { DataVersionProvider } from "../../app/DataVersion";
import { mockFetch, resetAuth } from "../../test/helpers";
import compareEB from "../../test/fixtures/compare_early_blind.json";
import compareScripted from "../../test/fixtures/compare_scripted.json";
import experiments from "../../test/fixtures/experiments_u7.json";
import runs from "../../test/fixtures/runs_u7.json";
import survScripted from "../../test/fixtures/survival_scripted.json";
import survEarly from "../../test/fixtures/survival_early.json";
import { buildOverlayOption, buildSurvivalOption, hazardMarks, overlayLines, pointsOf, survivalData } from "./charts";
import { CompareView, parseRuns } from "./CompareView";
import { censorText } from "./SurvivalPanel";

// jsdom has no canvas: the chart becomes a stub that exposes its option as JSON.
vi.mock("../../components/chart/LazyChart", () => ({
  LazyChart: ({ label, option }: { label: string; option: unknown }) => (
    <div data-testid="chart" role="img" aria-label={label} data-option={JSON.stringify(option)} />
  ),
}));

const EARLY = "minidb-v2-early-A-r00-338286d0";
const BLIND = "minidb-v3-blind-A-r00-013c5f62";
const SCRIPTED = ["pilot-export-csv-scripted-A-r00-8a533d8c", "pilot-export-csv-scripted-A-r01-8a533d8c"];
const cmp = (ids: string[]) => `/compare?runs=${encodeURIComponent(ids.join(","))}`;
const eb = compareEB as unknown as CompareResponse;
const theme = { text: "#000", muted: "#555", grid: "#ddd", surface: "#fff", border: "#ccc", series: ["#1", "#2", "#3", "#4", "#5", "#6", "#7"] };

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
}

function renderCompare(url: string) {
  return render(
    <DataVersionProvider>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route
            path="/compare"
            element={
              <>
                <CompareView />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </DataVersionProvider>,
  );
}

const base = (extra: Record<string, unknown> = {}) => ({
  "/runs": runs,
  "/experiments": experiments,
  "/ingest/status": { store_exists: true, stale: false },
  [`/survival?experiment=minidb-v2-early`]: survEarly,
  ...extra,
});

beforeEach(() => {
  resetAuth();
  initToken();
});

describe("parseRuns", () => {
  it("accepts valid ids, dedupes, drops junk and caps at 8", () => {
    expect(parseRuns("a,b,a")).toEqual(["a", "b"]);
    expect(parseRuns("../etc,ok-1,<img src=x>")).toEqual(["ok-1"]);
    expect(parseRuns(null)).toEqual([]);
    expect(parseRuns(Array.from({ length: 12 }, (_, i) => `r${i}`).join(","))).toHaveLength(8);
  });
});

describe("CompareView with two ingested runs", () => {
  it("preselects from ?runs= and draws metric, cost and context overlays", async () => {
    const { calls } = mockFetch(base({ [cmp([EARLY, BLIND])]: compareEB }));
    renderCompare(`/compare?runs=${EARLY},${BLIND}`);
    await screen.findByRole("heading", { name: "Overlay" });
    expect(calls.some((c) => c.path === cmp([EARLY, BLIND]))).toBe(true);
    expect(screen.getByRole("checkbox", { name: new RegExp(EARLY) })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: new RegExp(BLIND) })).toBeChecked();
    expect(screen.getByRole("heading", { name: /Runs to compare \(2\/8\)/ })).toBeInTheDocument();

    await screen.findByRole("img", { name: /Kaplan-Meier survival/ });
    const charts = screen.getAllByTestId("chart");
    // metric, cost, context fill, then the survival chart
    expect(charts.map((c) => c.getAttribute("aria-label"))).toEqual([
      expect.stringContaining("Hidden pass rate (P)"),
      expect.stringContaining("Cumulative estimated cost"),
      expect.stringContaining("Context fill"),
      expect.stringContaining("Kaplan-Meier survival"),
    ]);
    const opt = JSON.parse(charts[0].getAttribute("data-option") as string);
    expect(opt.series.map((s: { name: string }) => s.name)).toEqual([EARLY, BLIND]);
    expect(opt.xAxis.name).toBe("minutes of agent time");
    // hazard markers on each run's series
    expect(opt.series[0].markLine.data.length).toBe(eb.runs[0].hazards.length);
    expect(screen.getByText(/estimated \(API-equivalent\), not a bill/)).toBeInTheDocument();
  });

  it("switches metric and x axis", async () => {
    mockFetch(base({ [cmp([EARLY, BLIND])]: compareEB }));
    renderCompare(`/compare?runs=${EARLY},${BLIND}`);
    await screen.findByRole("heading", { name: "Overlay" });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox", { name: "Metric" }), "R");
    await user.click(screen.getByRole("radio", { name: "checkpoint" }));
    const opt = JSON.parse(screen.getAllByTestId("chart")[0].getAttribute("data-option") as string);
    expect(opt.yAxis.name).toBe("R");
    expect(opt.xAxis.name).toBe("checkpoint k");
    expect(opt.series[0].data[0][0]).toBe(1); // first checkpoint
    await user.click(screen.getByRole("checkbox", { name: "Hazard markers" }));
    const off = JSON.parse(screen.getAllByTestId("chart")[0].getAttribute("data-option") as string);
    expect(off.series[0].markLine).toBeUndefined();
  });

  it("shows the delta table against the first run and a hazard table", async () => {
    mockFetch(base({ [cmp([EARLY, BLIND])]: compareEB }));
    renderCompare(`/compare?runs=${EARLY},${BLIND}`);
    const table = await screen.findByRole("table", { name: /Final values and differences/ });
    expect(within(table).getByText("base")).toBeInTheDocument();
    expect(within(table).getByText("Cost (estimated, API-equivalent)")).toBeInTheDocument();
    const pRow = within(table).getByText("Hidden pass rate").closest("tr") as HTMLElement;
    const pd = eb.metric_deltas.find((m) => m.metric === "P")!;
    const diff = pd.delta_vs_base[BLIND]!;
    expect(within(pRow).getByText(new RegExp(`^${diff > 0 ? "\\+" : "−"}`))).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: `Hazards (${eb.runs.flatMap((r) => r.hazards).length})` })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Hazards of the selected runs" })).toBeInTheDocument();
  });

  it("selecting a run updates the URL and refetches", async () => {
    const { calls } = mockFetch(base({ [cmp([EARLY, BLIND])]: compareEB, [cmp([EARLY])]: { ...compareEB, run_ids: [EARLY], runs: [eb.runs[0]], base: EARLY } }));
    renderCompare(`/compare?runs=${EARLY},${BLIND}`);
    await screen.findByRole("heading", { name: "Overlay" });
    await userEvent.click(screen.getByRole("checkbox", { name: new RegExp(BLIND) }));
    await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent(`?runs=${EARLY}`));
    await waitFor(() => expect(calls.some((c) => c.path === cmp([EARLY]))).toBe(true));
    expect(await screen.findByText(/One run selected/)).toBeInTheDocument();
  });

  it("limits the selection to 8 runs", async () => {
    mockFetch(base({}));
    renderCompare(`/compare?runs=${(runs.runs as { run_id: string }[]).slice(0, 8).map((r) => r.run_id).join(",")}`);
    await screen.findByRole("heading", { name: /Runs to compare \(8\/8\)/ });
    const boxes = screen.getAllByRole("checkbox").filter((b) => !(b as HTMLInputElement).checked);
    expect(boxes.length).toBeGreaterThan(0);
    boxes.forEach((b) => expect(b).toBeDisabled());
  });
});

describe("CompareView states", () => {
  it("asks to pick runs when there is no selection, but still offers survival", async () => {
    mockFetch(base({ "/survival?experiment=minidb-v3-pilot-haiku": { ...survEarly, experiment: "minidb-v3-pilot-haiku" } }));
    renderCompare("/compare");
    expect(await screen.findByText("Pick runs to compare")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /Survival/ })).toBeInTheDocument();
  });

  it("says clearly when a run is not ingested and offers ingest", async () => {
    const notIngested = structuredClone(eb);
    notIngested.runs[1] = { ...notIngested.runs[1], ingested: false, series: {}, counters: {}, hazards: [] };
    notIngested.not_ingested = [BLIND];
    mockFetch(base({ [cmp([EARLY, BLIND])]: notIngested }));
    renderCompare(`/compare?runs=${EARLY},${BLIND}`);
    expect(await screen.findByText(/1 of these runs are in the metrics store/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ingest now" })).toBeInTheDocument();
    const opt = JSON.parse((await screen.findAllByTestId("chart"))[0].getAttribute("data-option") as string);
    expect(opt.series[1].data).toEqual([]);
  });

  it("when no selected run is ingested it draws nothing and says so", async () => {
    const none = structuredClone(eb);
    none.runs = none.runs.map((r) => ({ ...r, ingested: false, series: {}, counters: {}, hazards: [] }));
    none.metrics = [];
    none.metric_deltas = [];
    none.not_ingested = none.run_ids;
    mockFetch(base({ [cmp([EARLY, BLIND])]: none }));
    renderCompare(`/compare?runs=${EARLY},${BLIND}`);
    expect(await screen.findByText(/None of the selected runs is in the metrics store/)).toBeInTheDocument();
    expect(screen.getByText(/None of these runs is in the metrics store/)).toBeInTheDocument();
  });

  it("shows an error state when the comparison fails", async () => {
    mockFetch(base({ [cmp([EARLY, BLIND])]: () => ({ status: 404, body: { detail: "no such run" } }) }));
    renderCompare(`/compare?runs=${EARLY},${BLIND}`);
    expect(await screen.findByText("Could not load the comparison")).toBeInTheDocument();
  });

  it("renders hostile hazard evidence and names as text (UI-5)", async () => {
    const hostile = structuredClone(eb);
    hostile.runs[0].hazards[0].evidence = "<img src=x onerror=alert(1)>";
    hostile.runs[0].hazards[0].dimension = "<b>dim</b>";
    mockFetch(base({ [cmp([EARLY, BLIND])]: hostile }));
    const { container } = renderCompare(`/compare?runs=${EARLY},${BLIND}`);
    await screen.findByRole("table", { name: "Hazards of the selected runs" });
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getAllByText("<img src=x onerror=alert(1)>").length).toBeGreaterThan(0);
  });
});

describe("Survival panel", () => {
  it("shows median, bootstrap CI, censoring and the D-11 headline from the API", async () => {
    mockFetch(base({ [cmp(SCRIPTED)]: compareScripted, "/survival?experiment=pilot-export-csv-scripted": survScripted }));
    renderCompare(`/compare?runs=${SCRIPTED.join(",")}`);
    const table = await screen.findByRole("table", { name: /Survival summary/ });
    const g = (survScripted as unknown as SurvivalResponse).groups[0];
    const row = within(table).getByText(g.label).closest("tr") as HTMLElement;
    expect(within(row).getByText(g.headline_text)).toBeInTheDocument();
    expect(within(row).getByText(g.median_text as string)).toBeInTheDocument();
    expect(screen.getByText(/Small samples/)).toBeInTheDocument();
  });

  it("explains a missing store entry and offers to ingest", async () => {
    mockFetch(base({ "/survival?experiment=minidb-v2-early": () => ({ status: 404, body: { detail: "experiment not in the metrics store (ingest first)" } }) }));
    renderCompare("/compare");
    expect(await screen.findByText(/not in the metrics store, so there is no survival curve/)).toBeInTheDocument();
  });

  it("censorText lists reasons", () => {
    const g = { censored: 3, censored_by_reason: { budget: 2, deadline: 1 } } as never;
    expect(censorText(g)).toBe("3 (2 budget, 1 deadline)");
    expect(censorText({ censored: 0, censored_by_reason: {} } as never)).toBe("0");
  });
});

describe("chart option builders", () => {
  it("pointsOf uses k or minutes and skips nulls", () => {
    const s = { k: [1, 2, 3], t_s: [60, null, 180], value: [0.1, 0.2, null] };
    expect(pointsOf(s, "k")).toEqual([[1, 0.1], [2, 0.2]]);
    expect(pointsOf(s, "t")).toEqual([[1, 0.1]]);
    expect(pointsOf(undefined, "t")).toEqual([]);
  });

  it("hazard markers follow the axis", () => {
    const r = { hazards: [{ dimension: "quality", t_attributed_s: 600, k: 3, rule: "", t_detected_s: 0, evidence: "" }, { dimension: "cost", t_attributed_s: null, k: null, rule: "", t_detected_s: null, evidence: null }] } as never;
    expect(hazardMarks(r, "t")).toEqual([{ x: 10, label: "quality" }]);
    expect(hazardMarks(r, "k")).toEqual([{ x: 3, label: "quality" }]);
  });

  it("overlay option has one coloured series per run and the cost series values", () => {
    const lines = overlayLines(eb.runs, (r) => r.counters.cum_cost_usd, "t", theme.series, true);
    const opt = buildOverlayOption(lines, theme, { xName: "x", yName: "y" });
    expect(opt.series).toHaveLength(2);
    expect(opt.series[0].lineStyle.color).toBe("#1");
    expect(opt.series[1].data.at(-1)).toEqual(pointsOf(eb.runs[1].counters.cum_cost_usd, "t").at(-1));
    expect(opt.tooltip).not.toHaveProperty("formatter");
  });

  it("survival option reproduces the API's KM values exactly (step, CI band, censor ticks)", () => {
    const sv = survScripted as unknown as SurvivalResponse;
    const g = sv.groups[0];
    const d = survivalData(g)!;
    expect(d.step[0]).toEqual([0, 1]);
    expect(d.step.slice(1).map((p) => p[1])).toEqual(g.km!.surv);
    expect(d.step.slice(1).map((p) => p[0])).toEqual(g.km!.times.map((t) => t / 60));
    expect(d.lower.slice(1).map((p) => p[1])).toEqual(g.km!.lower);
    d.band.slice(1).forEach((p, i) => expect(p[1]).toBeCloseTo((g.km!.upper[i] ?? 1) - (g.km!.lower[i] ?? 0), 12));
    const opt = buildSurvivalOption(sv.groups, theme);
    expect(opt.series).toHaveLength(4);
    expect((opt.series[2] as { name: string }).name).toBe(g.label);
    expect((opt.series[2] as { step: string }).step).toBe("end");
    expect(opt.yAxis.max).toBe(1);
  });

  it("censor ticks and the headline marker come from the data", () => {
    const g = {
      label: "L1 / config A", available: true, headline_available: true, headline_s: 600, median_s: 1200,
      km: { times: [300, 900], surv: [0.8, 0.4], lower: [0.3, 0.1], upper: [0.99, 0.8], n_risk: [5, 3], n_event: [1, 1], censor_times: [700], censor_surv: [0.8] },
    } as never;
    const d = survivalData(g)!;
    expect(d.censors).toEqual([[700 / 60, 0.8]]);
    expect(d.headlineMin).toBe(10);
    const opt = buildSurvivalOption([g], theme);
    expect((opt.series[2] as { markLine: { data: { xAxis: number }[] } }).markLine.data[0].xAxis).toBe(10);
    expect(survivalData({ ...(g as object), available: false } as never)).toBeNull();
  });
});
