import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
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
});
