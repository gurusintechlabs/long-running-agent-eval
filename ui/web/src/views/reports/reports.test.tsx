import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initToken } from "../../api";
import { DataVersionProvider } from "../../app/DataVersion";
import reports from "../../test/fixtures/reports.json";
import { mockFetch, resetAuth } from "../../test/helpers";
import { inlineFigures } from "./DashboardPreview";
import { ReportsView } from "./ReportsView";

const EXP = "minidb-v2-early";
const OK = { ok: true, kind: "dashboard", exit_code: 0, output: "runs/reports/x/dashboard.html\n", duration_s: 3.1, stale_store: false, artifact: { name: "dashboard.html", bytes: 1, mtime: 1 } };

function renderReports() {
  return render(
    <DataVersionProvider>
      <MemoryRouter>
        <ReportsView />
      </MemoryRouter>
    </DataVersionProvider>,
  );
}

const withReports = (over: Record<string, unknown> = {}) => ({ ...reports, ...over });

beforeEach(() => {
  resetAuth();
  initToken();
});
afterEach(() => vi.unstubAllGlobals());

describe("ReportsView", () => {
  it("lists experiments with their artifacts and the cost wording", async () => {
    mockFetch({ "/reports": reports });
    renderReports();
    const card = (await screen.findByText(EXP)).closest("section") as HTMLElement;
    expect(within(card).getByText(/figures/)).toBeInTheDocument();
    expect(within(card).getByText("older than the store")).toBeInTheDocument(); // real data: reports predate the last ingest
    expect(within(card).getByRole("button", { name: "Open dashboard" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Open PDF" })).toBeEnabled();
    expect(screen.getByText(/estimated \(API-equivalent\), not a bill/)).toBeInTheDocument();
  });

  it("rebuilds the dashboard through the API and shows the output tail", async () => {
    const { calls } = mockFetch({ "/reports": reports, [`/reports/${EXP}/rebuild`]: OK });
    renderReports();
    const card = (await screen.findByText(EXP)).closest("section") as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: "Rebuild dashboard" }));
    expect(await within(card).findByText(/Built dashboard.html in 3.1s/)).toBeInTheDocument();
    const post = calls.find((c) => c.path === `/reports/${EXP}/rebuild`)!;
    expect(post.init?.method).toBe("POST");
    expect(JSON.parse(post.init?.body as string)).toEqual({ kind: "dashboard", allow_stale: false });
    expect(post.init?.headers).toMatchObject({ "X-LRAE-Token": "test-token" });
    await userEvent.click(within(card).getByText("Output"));
    expect(within(card).getByText(/dashboard.html/, { selector: "pre" })).toBeInTheDocument();
  });

  it("shows progress and blocks other rebuilds while one runs (single flight)", async () => {
    let release: (v: unknown) => void = () => undefined;
    const pending = new Promise((r) => (release = r));
    const { fn } = mockFetch({ "/reports": reports });
    const orig = fn.getMockImplementation()!;
    fn.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/rebuild")) {
        await pending;
        return new Response(JSON.stringify({ ...OK, kind: "pdf" }), { status: 200 });
      }
      return orig(input, init);
    });
    renderReports();
    const cards = await screen.findAllByRole("button", { name: "Rebuild PDF" });
    await userEvent.click(cards[0]);
    expect(await screen.findByText(/lrae report minidb-v2-early --pdf/)).toBeInTheDocument();
    for (const b of screen.getAllByRole("button", { name: /Rebuild/ })) expect(b).toBeDisabled();
    release(null);
    expect(await screen.findByText(/Built report.pdf/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Rebuild dashboard" })[0]).toBeEnabled());
  });

  it("offers re-ingest or rebuild-anyway when the store is stale", async () => {
    let n = 0;
    const { calls } = mockFetch({
      "/reports": reports,
      "/ingest": { ok: true, output: "ingested" },
      [`/reports/${EXP}/rebuild`]: () =>
        ++n === 1
          ? { status: 409, body: { detail: { code: "store_stale", message: "metrics store is stale: 1 run(s) are not in the store" } } }
          : { body: OK },
    });
    renderReports();
    const card = (await screen.findByText(EXP)).closest("section") as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: "Rebuild dashboard" }));
    expect(await within(card).findByText(/The metrics store is out of date/)).toBeInTheDocument();
    expect(within(card).getByText(/1 run\(s\) are not in the store/)).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "Rebuild anyway" }));
    await within(card).findByText(/Built dashboard.html/);
    const bodies = calls.filter((c) => c.path.endsWith("/rebuild")).map((c) => JSON.parse(c.init?.body as string));
    expect(bodies).toEqual([{ kind: "dashboard", allow_stale: false }, { kind: "dashboard", allow_stale: true }]);
  });

  it("re-ingests first, then rebuilds", async () => {
    let n = 0;
    const { calls } = mockFetch({
      "/reports": reports,
      "/ingest": { ok: true, output: "ingested 3 runs" },
      [`/reports/${EXP}/rebuild`]: () => (++n === 1 ? { status: 409, body: { detail: { code: "store_stale", message: "stale" } } } : { body: OK }),
    });
    renderReports();
    const card = (await screen.findByText(EXP)).closest("section") as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: "Rebuild dashboard" }));
    await userEvent.click(await within(card).findByRole("button", { name: "Re-ingest, then rebuild" }));
    await within(card).findByText(/Built dashboard.html/);
    expect(calls.map((c) => c.path).filter((p) => p === "/ingest" || p.endsWith("/rebuild"))).toEqual([`/reports/${EXP}/rebuild`, "/ingest", `/reports/${EXP}/rebuild`]);
  });

  it("explains a missing Chrome and disables the PDF button", async () => {
    mockFetch({ "/reports": withReports({ chrome: { available: false, error: "headless Chrome not found; install Google Chrome/Chromium or set LRAE_CHROME" } }) });
    renderReports();
    await screen.findByText(EXP);
    for (const b of screen.getAllByRole("button", { name: "Rebuild PDF" })) expect(b).toBeDisabled();
    expect(screen.getAllByText(/PDF needs headless Chrome/).length).toBeGreaterThan(0);
  });

  it("shows the failing command output", async () => {
    mockFetch({ "/reports": reports, [`/reports/${EXP}/rebuild`]: () => ({ status: 500, body: { ...OK, ok: false, exit_code: 1, output: "Traceback (most recent call last):\nboom" } }) });
    renderReports();
    const card = (await screen.findByText(EXP)).closest("section") as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: "Rebuild dashboard" }));
    expect(await within(card).findByText("Build failed.")).toBeInTheDocument();
    expect(within(card).getByText(/boom/, { selector: "pre" })).toBeInTheDocument();
  });

  it("shows the stale-store hint with a re-ingest button on the page", async () => {
    mockFetch({ "/reports": withReports({ ingest: { ...reports.ingest, stale: true, reason: "2 run(s) are not in the store" } }), "/ingest": { ok: true, output: "ok" } });
    renderReports();
    expect(await screen.findByText(/2 run\(s\) are not in the store/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-ingest now" })).toBeInTheDocument();
  });

  it("renders hostile experiment ids as text (UI-5)", async () => {
    const hostile = structuredClone(reports);
    hostile.experiments[0].experiment_id = "<img src=x onerror=alert(1)>";
    mockFetch({ "/reports": hostile });
    const { container } = renderReports();
    await screen.findByText("<img src=x onerror=alert(1)>");
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows the dashboard in a fully sandboxed iframe with figures inlined", async () => {
    const html = '<h1>dash</h1><img src="figures/survival.png" alt="s"><img src="figures/unknown.png">';
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const u = String(input);
      if (u.startsWith("/api/reports/minidb-v2-early/file?name=dashboard.html")) return new Response(html);
      if (u.includes("name=figures%2Fsurvival.png")) return { ok: true, status: 200, blob: async () => new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" }) };
      if (u === "/api/reports") return new Response(JSON.stringify(reports));
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchFn);
    renderReports();
    const card = (await screen.findByText(EXP)).closest("section") as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: "Open dashboard" }));
    const frame = (await within(card).findByTitle(`Dashboard of ${EXP}`)) as HTMLIFrameElement;
    expect(frame.getAttribute("sandbox")).toBe("");
    const doc = frame.getAttribute("srcdoc") as string;
    expect(doc).toContain('src="data:image/png;base64,');
    expect(doc).toContain('src="figures/unknown.png"'); // never fetched: not in the listing
    const call = (fetchFn.mock.calls as unknown as [RequestInfo, RequestInit][]).find((c) => String(c[0]).includes("dashboard.html"))!;
    expect(call[1].headers).toMatchObject({ "X-LRAE-Token": "test-token" });
  });
});

describe("inlineFigures", () => {
  it("only rewrites listed figure names", async () => {
    const out = await inlineFigures('<img src="figures/a.png"><img src=\'figures/b.png\'><img src="http://evil/x.png"><img src="figures/../x.png">', new Map([["figures/a.png", "data:image/png;base64,AA"]]));
    expect(out).toContain('src="data:image/png;base64,AA"');
    expect(out).toContain("src='figures/b.png'");
    expect(out).toContain('src="http://evil/x.png"');
    expect(out).toContain('src="figures/../x.png"');
  });
});
