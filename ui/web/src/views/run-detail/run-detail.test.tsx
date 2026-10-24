import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { initToken } from "../../api";
import { fx, mockFetch, renderRoute, resetAuth } from "../../test/helpers";
import { RunDetailView } from "./RunDetailView";

// jsdom has no canvas: replace the chart with a labelled stub (the option builder is tested separately).
vi.mock("../../components/chart/LazyChart", () => ({
  LazyChart: ({ label }: { label: string }) => <div data-testid="chart" role="img" aria-label={label} />,
}));

const HOSTILE = "<img src=x onerror=alert(1)>";
const early = fx.runEarly.run.run_id;
const haiku = fx.runHaiku.run.run_id;

beforeEach(() => {
  resetAuth();
  initToken();
});

function routes(detail: unknown, cps: unknown, id: string) {
  return mockFetch({
    [`/runs/${id}`]: detail,
    [`/runs/${id}/checkpoints`]: cps,
    "/ingest/status": fx.ingestStatus,
  });
}

describe("RunDetailView, ingested run", () => {
  it("shows header, charts, checkpoints and hazards from the fixture", async () => {
    routes(fx.runEarly, fx.checkpointsEarly, early);
    renderRoute(<RunDetailView />, `/runs/${early}`, "/runs/:runId");
    await screen.findByRole("heading", { name: early });

    // header
    expect(screen.getByText("claude-opus-5-5")).toBeInTheDocument();
    expect(screen.getByText("2.1.301")).toBeInTheDocument();
    expect(screen.getByText("338286d03f5a")).toBeInTheDocument(); // short spec hash
    expect(screen.getByText("53b58af0b1b0")).toBeInTheDocument(); // short seed commit
    expect(screen.getByText("local")).toBeInTheDocument();
    expect(screen.getByText("not recorded")).toBeInTheDocument(); // safe mode absent in this manifest
    expect(screen.getByText("BUDGET_EXHAUSTED")).toBeInTheDocument();
    expect(screen.getByText(/estimated \(API-equivalent\)/)).toBeInTheDocument();

    // one chart per core metric by default
    const charts = await screen.findAllByTestId("chart");
    expect(charts).toHaveLength(7);

    // hazards stay on the overview
    expect(screen.getByRole("heading", { name: "Hazards (2)" })).toBeInTheDocument();
    expect(screen.getByText("C>0")).toBeInTheDocument();
    expect(screen.getByText("S_int=1.3245 > 2.0 x baseline 0.5436")).toBeInTheDocument();

    // checkpoints table (with metric columns) lives in its own tab
    await userEvent.click(screen.getByRole("tab", { name: "Checkpoints" }));
    const table = await screen.findByRole("table", { name: "Checkpoints" });
    expect(within(table).getAllByRole("row")).toHaveLength(1 + fx.checkpointsEarly.checkpoints.length);
    expect(within(table).getByRole("button", { name: "Sort by Hidden pass rate" })).toBeInTheDocument();
  });

  it("lets the metric picker add and remove charts", async () => {
    routes(fx.runEarly, fx.checkpointsEarly, early);
    renderRoute(<RunDetailView />, `/runs/${early}`, "/runs/:runId");
    await screen.findAllByTestId("chart");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "P", pressed: true }));
    expect(screen.getAllByTestId("chart")).toHaveLength(6);
    await user.click(screen.getByRole("button", { name: "tests_tampered" }));
    expect(screen.getAllByTestId("chart")).toHaveLength(7);
    await user.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getAllByTestId("chart").length).toBeGreaterThan(7);
  });

  it("renders hostile hazard evidence and run ids as text (UI-5)", async () => {
    const detail = structuredClone(fx.runEarly);
    detail.hazards[0].evidence = HOSTILE;
    detail.hazards[0].rule = HOSTILE;
    const { container } = (routes(detail, fx.checkpointsEarly, early), renderRoute(<RunDetailView />, `/runs/${early}`, "/runs/:runId"));
    await screen.findByRole("heading", { name: early });
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getAllByText(HOSTILE)).toHaveLength(2);
  });
});

describe("RunDetailView, run not ingested yet", () => {
  it("explains it, offers re-ingest, and still lists checkpoints from the logs", async () => {
    const { calls } = routes(fx.runHaiku, fx.checkpointsHaiku, haiku);
    mockFetch({
      [`/runs/${haiku}`]: fx.runHaiku,
      [`/runs/${haiku}/checkpoints`]: fx.checkpointsHaiku,
      "/ingest/status": fx.ingestStatus,
      "/ingest": () => ({ body: { ok: true, output: "ingested 12 runs" } }),
    });
    void calls;
    renderRoute(<RunDetailView />, `/runs/${haiku}`, "/runs/:runId");
    await screen.findByRole("heading", { name: "Not ingested yet" });
    expect(screen.queryAllByTestId("chart")).toHaveLength(0);
    expect(screen.getByText(/why: task\.workspace_memory/)).toBeInTheDocument(); // safe_mode is an object in real manifests
    expect(screen.queryByText(/object Object/)).toBeNull();
    expect(screen.getByText("Hazards need ingest")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Checkpoints" }));
    expect(await screen.findByRole("heading", { name: `Checkpoints (${fx.checkpointsHaiku.checkpoints.length})` })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Overview" }));

    await userEvent.click(screen.getByRole("button", { name: "Re-ingest now" }));
    expect(await screen.findByText("Ingest finished.")).toBeInTheDocument();
    expect(screen.getByText("ingested 12 runs")).toBeInTheDocument();
  });

  it("shows a friendly message for an unknown run", async () => {
    mockFetch({ "/runs/ghost": () => ({ status: 404, body: { detail: "no such run" } }), "/runs/ghost/checkpoints": () => ({ status: 404, body: {} }) });
    renderRoute(<RunDetailView />, "/runs/ghost", "/runs/:runId");
    expect(await screen.findByText("No such run")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /All runs/ })).toHaveAttribute("href", "/runs");
  });
});
