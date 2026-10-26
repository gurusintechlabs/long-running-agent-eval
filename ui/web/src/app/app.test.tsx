import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initToken } from "../api";
import { App } from "../App";
import { fx, mockFetch, resetAuth } from "../test/helpers";

beforeEach(() => {
  window.history.replaceState(null, "", "/runs");
});

describe("access", () => {
  it("shows the open-the-printed-URL screen when there is no token, without calling the API", () => {
    resetAuth(null);
    const { fn } = mockFetch({});
    render(<App />);
    expect(screen.getByRole("heading", { name: /open the url printed by lrae ui/i })).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
  });

  it("switches to that screen when the server answers 401", async () => {
    resetAuth("stale-token");
    initToken();
    mockFetch({
      "/runs": () => ({ status: 401, body: { detail: "missing or wrong token" } }),
      "/experiments": () => ({ status: 401, body: { detail: "x" } }),
      "/ingest/status": () => ({ status: 401, body: { detail: "x" } }),
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: /open the url printed by lrae ui/i })).toBeInTheDocument();
  });
});

describe("shell and stale banner", () => {
  const table = { "/runs": fx.runs, "/experiments": fx.experiments, "/ingest/status": fx.ingestStatus };

  it("navigates to another view from the sidebar", async () => {
    resetAuth();
    initToken();
    mockFetch(table);
    render(<App />);
    await screen.findByText("12 of 12 runs");
    await userEvent.click(screen.getByRole("link", { name: /Compare/ }));
    expect(await screen.findByRole("heading", { name: "Compare" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Compare/ })).toHaveClass("active");
  });

  it("shows the stale banner and re-ingests with a result", async () => {
    resetAuth();
    initToken();
    let status = fx.ingestStatus as unknown;
    const { calls } = mockFetch({
      ...table,
      "/ingest/status": () => ({ body: status }),
      "/ingest": () => {
        status = { ...fx.ingestStatus, stale: false, reason: null, runs_in_store: 12, missing_from_store: [] };
        return { body: { ok: true, output: "done" } };
      },
    });
    render(<App />);
    await screen.findByText(/metrics store is out of date/i);
    expect(screen.getByText(/4 run\(s\) are not in the store/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Re-ingest now" }));
    expect(await screen.findByText("Ingest finished.")).toBeInTheDocument();
    expect(screen.getByText("done")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/ingest" && c.init?.method === "POST")).toBe(true);
    await waitFor(() => expect(screen.queryByText(/metrics store is out of date/i)).not.toBeInTheDocument());
  });

  describe("with the server's auto-ingest", () => {
    afterEach(() => {
      vi.useRealTimers();
    });
    const autoOn = { enabled: true, running: false, ingests: 1, last_ok: true, last_error: null };

    it("shows no banner while the store catches up, and reloads views when a new store lands", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      resetAuth();
      initToken();
      let status: Record<string, unknown> = { ...fx.ingestStatus, auto: autoOn };
      let runs = fx.runs as { runs: unknown[] };
      const { calls } = mockFetch({ ...table, "/runs": () => ({ body: runs }), "/ingest/status": () => ({ body: status }) });
      render(<App />);
      await screen.findByText("12 of 12 runs");
      expect(screen.queryByText(/metrics store is out of date/i)).not.toBeInTheDocument();
      const before = calls.filter((c) => c.path === "/runs").length;
      // the server's ingest finished: a new store file, one run fewer on screen afterwards
      runs = { ...fx.runs, runs: fx.runs.runs.slice(1) };
      status = { ...status, stale: false, reason: null, store_epoch: (fx.ingestStatus.store_epoch as number) + 60 };
      await vi.advanceTimersByTimeAsync(5100);
      await waitFor(() => expect(calls.filter((c) => c.path === "/runs").length).toBeGreaterThan(before));
      expect(await screen.findByText("11 of 11 runs")).toBeInTheDocument();
      // the list never went back to a loading state while it re-fetched
      expect(screen.queryByText(/loading runs/i)).not.toBeInTheDocument();
    });

    it("shows a retry banner when the background ingest failed", async () => {
      resetAuth();
      initToken();
      mockFetch({
        ...table,
        "/ingest/status": () => ({ body: { ...fx.ingestStatus, auto: { ...autoOn, last_ok: false, last_error: "boom: bad scorer.jsonl" } } }),
      });
      render(<App />);
      expect(await screen.findByText(/updating the metrics store failed/i)).toBeInTheDocument();
      expect(screen.getByText("boom: bad scorer.jsonl")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Retry now" })).toBeInTheDocument();
    });
  });
});
