import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { initToken, type RunSummary } from "../../api";
import { fx, mockFetch, renderRoute, resetAuth } from "../../test/helpers";
import { filterRuns, NO_FILTERS, runDuration } from "./filter";
import { RunsView } from "./RunsView";

const HOSTILE = "<img src=x onerror=alert(1)>";

function tableRunIds(): string[] {
  const rows = screen.getAllByRole("row").slice(1);
  return rows.map((r) => within(r).getAllByRole("link")[0].textContent ?? "");
}

beforeEach(() => {
  resetAuth();
  initToken();
});

describe("filterRuns", () => {
  const runs = fx.runs.runs as RunSummary[];
  it("searches across id, experiment and model, all tokens required", () => {
    expect(filterRuns(runs, { ...NO_FILTERS, search: "haiku" }).map((r) => r.experiment_id)).toEqual(["minidb-v3-pilot-haiku"]);
    expect(filterRuns(runs, { ...NO_FILTERS, search: "canary killed" })).toHaveLength(2);
    expect(filterRuns(runs, { ...NO_FILTERS, search: "nonexistent" })).toHaveLength(0);
  });
  it("filters by state, ingested and live", () => {
    expect(filterRuns(runs, { ...NO_FILTERS, state: "KILLED" })).toHaveLength(2);
    expect(filterRuns(runs, { ...NO_FILTERS, ingested: "no" })).toHaveLength(4);
    expect(filterRuns(runs, { ...NO_FILTERS, liveOnly: true })).toHaveLength(0);
  });
  it("derives duration from timestamps for runs that are not ingested", () => {
    const r = runs.find((x) => !x.ingested)!;
    expect(runDuration(r)).toBeCloseTo(r.end_epoch! - r.start_epoch!);
  });
});

describe("RunsView", () => {
  const table = { "/runs": fx.runs, "/experiments": fx.experiments, "/ingest/status": fx.ingestStatus };

  it("lists every run, newest first, with the cost labelled as an estimate", async () => {
    mockFetch(table);
    renderRoute(<RunsView />, "/runs", "/runs");
    await screen.findByText("12 of 12 runs");
    expect(tableRunIds()[0]).toBe("minidb-v3-pilot-haiku-A-r00-f47fe80e");
    expect(screen.getByText(/estimated \(API-equivalent\)/)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /est\. cost/i })).toBeInTheDocument();
  });

  it("sorts by a column, toggling direction", async () => {
    mockFetch(table);
    renderRoute(<RunsView />, "/runs", "/runs");
    await screen.findByText("12 of 12 runs");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Sort by Est\. cost/ }));
    expect(tableRunIds()[0]).toMatch(/^(canary|snapshot)/); // cheapest first
    await user.click(screen.getByRole("button", { name: /Sort by Est\. cost/ }));
    expect(tableRunIds()[0]).toBe("minidb-v2-early-A-r00-338286d0"); // $40 first
    expect(screen.getByRole("columnheader", { name: /est\. cost/i })).toHaveAttribute("aria-sort", "descending");
  });

  it("filters by search text and shows an empty state with a way back", async () => {
    mockFetch(table);
    renderRoute(<RunsView />, "/runs", "/runs");
    await screen.findByText("12 of 12 runs");
    const user = userEvent.setup();
    await user.type(screen.getByRole("searchbox"), "canary");
    expect(screen.getByText("2 of 12 runs")).toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(screen.getByText("No runs match")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Clear filters" })[0]);
    expect(screen.getByText("12 of 12 runs")).toBeInTheDocument();
  });

  it("groups by experiment", async () => {
    mockFetch(table);
    renderRoute(<RunsView />, "/runs", "/runs");
    await screen.findByText("12 of 12 runs");
    await userEvent.click(screen.getByRole("checkbox", { name: "Group by experiment" }));
    expect(screen.getByRole("heading", { name: "pilot-export-csv-scripted" })).toBeInTheDocument();
    expect(screen.getAllByRole("table")).toHaveLength(fx.experiments.experiments.length);
  });

  it("renders hostile names as text, never as markup (UI-5)", async () => {
    const evil = {
      runs: [{ ...(fx.runs.runs[0] as RunSummary), run_id: HOSTILE, experiment_id: HOSTILE, model: HOSTILE }],
    };
    mockFetch({ ...table, "/runs": evil });
    const { container } = renderRoute(<RunsView />, "/runs", "/runs");
    await screen.findByText("1 of 1 runs");
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getAllByText(HOSTILE).length).toBeGreaterThanOrEqual(2);
  });

  it("polls while a run is live", async () => {
    const live = { runs: [{ ...(fx.runs.runs[0] as RunSummary), live: true, state: "RUNNING" }] };
    const { fn } = mockFetch({ ...table, "/runs": live });
    renderRoute(<RunsView />, "/runs", "/runs");
    await screen.findByText(/refreshing every few seconds/);
    expect(screen.getByText("(live)")).toBeInTheDocument();
    await waitFor(() => expect(fn).toHaveBeenCalled());
  });
});
