import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { initToken, type PreviewResponse, type RunDetail } from "../../api";
import { ControlBar } from "../../app/ControlBar";
import { DataVersionProvider } from "../../app/DataVersion";
import { mockFetch, renderRoute, resetAuth } from "../../test/helpers";
import checkpoints from "../../test/fixtures/checkpoints_scripted.json";
import controlIdle from "../../test/fixtures/control_idle.json";
import previewReal from "../../test/fixtures/preview_real.json";
import previewScripted from "../../test/fixtures/preview_scripted.json";
import runScripted from "../../test/fixtures/run_scripted.json";
import specs from "../../test/fixtures/specs.json";
import { LaunchView } from "./LaunchView";
import { RunActions } from "./RunActions";

const HOSTILE = "<img src=x onerror=alert(1)>";
const RUN_ID = runScripted.run.run_id;

const active = {
  ...controlIdle,
  active: true,
  launch_allowed: false,
  reason: "a harness process is alive (pid 4242); one run at a time",
  run: { run_id: "other-run-A-r00-abc", pid: 4242, state: "running", source: "tracked-run", verified: true },
  job: { kind: "run", pid: 4242, started_epoch: 1.8e9, alive: true, exit_code: null, run_ids: ["other-run-A-r00-abc"] },
  log_tail: "harness booting\nline two",
};

beforeEach(() => {
  resetAuth();
  initToken();
});

const R = (body: unknown, status = 200) => () => ({ status, body });
type H = (init: RequestInit | undefined) => { status?: number; body: unknown };
const err = (status: number, code: string, message: string, extra: object = {}) => ({ status, body: { detail: { code, message, ...extra } } });
const bodyOf = (calls: { path: string; init?: RequestInit }[], path: string) => JSON.parse(String(calls.filter((c) => c.path === path).at(-1)?.init?.body ?? "null"));

/** Launch view with a spec chosen and previewed. `preview` is the preview response; `extra` more routes. */
async function previewSpec(preview: unknown, extra: Record<string, unknown | H> = {}, control: unknown = controlIdle, specName = "pilot-scripted") {
  const m = mockFetch({
    "/specs": specs,
    "/control/state": control,
    "/launch/preview": preview,
    ...extra,
  });
  const user = userEvent.setup();
  renderRoute(<LaunchView />, "/launch", "/launch");
  const select = await screen.findByLabelText("Spec");
  const path = specs.specs.find((s) => s.name === specName)!.path;
  await user.selectOptions(select, path);
  await user.click(screen.getByRole("button", { name: "Preview estimate" }));
  await screen.findByText(/2\. Estimate/);
  return { user, m };
}

describe("Launch preview", () => {
  it("shows a scripted estimate as no-spend, with the server's figures", async () => {
    const { m } = await previewSpec(previewScripted);
    expect(screen.getByText("No spend")).toBeInTheDocument();
    expect(screen.getByText(/Scripted runtime: no model calls, no spend/)).toBeInTheDocument();
    expect(screen.getByTestId("max-spend")).toHaveTextContent("$2.00");
    expect(screen.getByTestId("run-count")).toHaveTextContent("2");
    for (const id of previewScripted.estimate.run_ids) expect(screen.getByText(id)).toBeInTheDocument();
    expect(screen.getByText("spec validates (lrae validate)")).toBeInTheDocument();
    expect(screen.getAllByText("pass")).toHaveLength(2);
    expect(screen.queryByText("REAL SPEND")).not.toBeInTheDocument();
    // the request carried only the spec reference
    expect(bodyOf(m.calls, "/launch/preview")).toEqual({ spec_path: "spec/examples/pilot-scripted.yaml" });
  });

  it("sends config and repeat when entered", async () => {
    const { user, m } = await previewSpec(previewScripted);
    await user.type(screen.getByLabelText("Config (optional)"), "A");
    await user.type(screen.getByLabelText("Repeat (optional)"), "0, 1");
    await user.click(screen.getByRole("button", { name: "Preview estimate" }));
    await waitFor(() => expect(bodyOf(m.calls, "/launch/preview")).toEqual({ spec_path: "spec/examples/pilot-scripted.yaml", config: "A", repeat: [0, 1] }));
  });

  it("rejects a malformed repeat client-side", async () => {
    mockFetch({ "/specs": specs, "/control/state": controlIdle });
    const user = userEvent.setup();
    renderRoute(<LaunchView />, "/launch", "/launch");
    await user.selectOptions(await screen.findByLabelText("Spec"), "spec/examples/pilot-scripted.yaml");
    await user.type(screen.getByLabelText("Repeat (optional)"), "a,b");
    expect(screen.getByText(/whole numbers/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview estimate" })).toBeDisabled();
  });

  it("shows a real-spend estimate prominently", async () => {
    await previewSpec(previewReal, {}, controlIdle, "minidb-v3");
    expect(screen.getByText("REAL SPEND")).toBeInTheDocument();
    expect(screen.getByText(/uses the real claude_code runtime and spends real money/)).toBeInTheDocument();
    expect(screen.getByTestId("max-spend")).toHaveTextContent("$1250");
    expect(screen.getByTestId("run-count")).toHaveTextContent("5");
    expect(screen.getByText(/agent runtime claude_code uses the Claude subscription/)).toBeInTheDocument();
    expect(screen.getAllByText("claude-opus-5-5").length).toBeGreaterThan(0);
    expect(screen.getByText(/API-equivalent estimates/)).toBeInTheDocument();
  });

  it("shows the server's text on a failed preview (422) and offers no estimate", async () => {
    mockFetch({
      "/specs": specs,
      "/control/state": controlIdle,
      "/launch/preview": () => err(422, "spec_invalid", `spec invalid: ${HOSTILE}`),
    });
    const user = userEvent.setup();
    renderRoute(<LaunchView />, "/launch", "/launch");
    await user.selectOptions(await screen.findByLabelText("Spec"), "spec/examples/pilot-scripted.yaml");
    await user.click(screen.getByRole("button", { name: "Preview estimate" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("spec_invalid");
    expect(alert).toHaveTextContent(HOSTILE);
    expect(alert.querySelector("img")).toBeNull();
    expect(screen.queryByText(/2\. Estimate/)).not.toBeInTheDocument();
  });

  it("renders hostile strings from the server as text", async () => {
    const hostile: PreviewResponse = JSON.parse(JSON.stringify(previewScripted));
    hostile.estimate.experiment_id = HOSTILE;
    hostile.checks.push({ name: HOSTILE, ok: false, detail: HOSTILE });
    hostile.warnings = [HOSTILE, { code: "w", message: HOSTILE }];
    hostile.conflicts = [{ weird: HOSTILE }];
    await previewSpec(hostile);
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getAllByText(HOSTILE, { exact: false }).length).toBeGreaterThan(3);
    expect(screen.getByText("FAIL")).toBeInTheDocument();
  });

  it("links to the Specs editor and groups examples and drafts", async () => {
    mockFetch({ "/specs": specs, "/control/state": controlIdle });
    renderRoute(<LaunchView />, "/launch", "/launch");
    expect(await screen.findByRole("link", { name: "Open the Specs editor" })).toHaveAttribute("href", "/specs");
    expect(screen.getByRole("group", { name: "Examples" })).toBeInTheDocument();
  });
});

describe("Scripted launch", () => {
  it("needs a dialog confirmation, sends only the nonce, then opens the run", async () => {
    const { user, m } = await previewSpec(previewScripted, {
      "/launch": R({ started: true, manifest_seen: true, pid: 1, run_id: "pilot-x", run_ids: ["pilot-x"], log: "l.log" }),
    });
    await user.click(screen.getByRole("button", { name: /Review and launch/ }));
    const dlg = screen.getByRole("dialog", { name: "Confirm launch" });
    expect(within(dlg).queryByLabelText(/Maximum spend/)).not.toBeInTheDocument();
    // nothing was launched by merely opening the dialog
    expect(m.calls.some((c) => c.path === "/launch")).toBe(false);
    await user.click(within(dlg).getByRole("button", { name: "Launch" }));
    await screen.findByText("elsewhere"); // navigated away from /launch
    expect(bodyOf(m.calls, "/launch")).toEqual({ nonce: previewScripted.confirmation_nonce });
  });

  it("Esc closes the dialog without launching and returns focus to the opener", async () => {
    const { user, m } = await previewSpec(previewScripted);
    const opener = screen.getByRole("button", { name: /Review and launch/ });
    await user.click(opener);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(m.calls.some((c) => c.path === "/launch")).toBe(false);
  });

  it("keeps Tab focus inside the dialog", async () => {
    const { user } = await previewSpec(previewScripted);
    await user.click(screen.getByRole("button", { name: /Review and launch/ }));
    const dlg = screen.getByRole("dialog");
    for (let i = 0; i < 8; i++) {
      await user.tab();
      expect(dlg.contains(document.activeElement)).toBe(true);
    }
    await user.tab({ shift: true });
    expect(dlg.contains(document.activeElement)).toBe(true);
  });

  it("202: keeps polling the control state and navigates when the run id appears", async () => {
    let n = 0;
    const { user } = await previewSpec(previewScripted, {
      "/launch": R({ started: true, manifest_seen: false, pid: 9, run_ids: ["pilot-x"] }, 202),
      "/control/state": () => {
        n += 1;
        return { body: n < 3 ? controlIdle : { ...active, run: { ...active.run, run_id: "pilot-x" } } };
      },
    });
    await user.click(screen.getByRole("button", { name: /Review and launch/ }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Launch" }));
    await screen.findByText("Waiting for the run to appear");
    await screen.findByText("elsewhere", undefined, { timeout: 15000 });
  }, 20000);
});

describe("Real-spend typed confirmation", () => {
  async function openReal() {
    const r = await previewSpec(previewReal, { "/launch": R({ started: true, manifest_seen: true, pid: 2, run_id: "r1", run_ids: ["r1"] }) }, controlIdle, "minidb-v3");
    await r.user.click(screen.getByRole("button", { name: /confirm real-spend launch/ }));
    const dlg = screen.getByRole("dialog", { name: "Confirm real-spend launch" });
    return { ...r, dlg };
  }

  it("is disabled until both figures match; empty, wrong and half-right keep it disabled; fields are not prefilled", async () => {
    const { user, dlg, m } = await openReal();
    const usd = within(dlg).getByLabelText(/Maximum spend in USD/);
    const runs = within(dlg).getByLabelText(/Number of runs/);
    const go = within(dlg).getByRole("button", { name: /Launch \(real spend/ });
    expect(usd).toHaveValue("");
    expect(runs).toHaveValue("");
    expect(go).toBeDisabled();
    await user.type(usd, "1250");
    expect(go).toBeDisabled(); // runs still empty
    await user.type(runs, "4");
    expect(go).toBeDisabled(); // wrong runs
    await user.clear(runs);
    await user.type(runs, "5");
    expect(go).toBeEnabled();
    await user.clear(usd);
    await user.type(usd, "125");
    expect(go).toBeDisabled(); // wrong USD
    await user.clear(usd);
    await user.type(usd, "abc");
    expect(go).toBeDisabled();
    await user.clear(usd);
    await user.type(usd, "$1250.00");
    expect(go).toBeEnabled();
    expect(m.calls.some((c) => c.path === "/launch")).toBe(false);
  });

  it("sends the typed figures with the nonce", async () => {
    const { user, dlg, m } = await openReal();
    await user.type(within(dlg).getByLabelText(/Maximum spend in USD/), "1250");
    await user.type(within(dlg).getByLabelText(/Number of runs/), "5");
    await user.click(within(dlg).getByRole("button", { name: /Launch \(real spend/ }));
    await screen.findByText("elsewhere");
    expect(bodyOf(m.calls, "/launch")).toEqual({ nonce: previewReal.confirmation_nonce, confirm_usd: 1250, confirm_runs: 5 });
  });

  it("Enter in the field cannot submit while invalid", async () => {
    const { user, dlg, m } = await openReal();
    await user.type(within(dlg).getByLabelText(/Maximum spend in USD/), "1{Enter}");
    expect(m.calls.some((c) => c.path === "/launch")).toBe(false);
  });

  it("shows the server's 422 text and stays usable", async () => {
    const { user, dlg } = await (async () => {
      const r = await previewSpec(previewReal, { "/launch": () => err(422, "confirmation_mismatch", `typed figures do not match ${HOSTILE}`) }, controlIdle, "minidb-v3");
      await r.user.click(screen.getByRole("button", { name: /confirm real-spend launch/ }));
      return { ...r, dlg: screen.getByRole("dialog") };
    })();
    await user.type(within(dlg).getByLabelText(/Maximum spend in USD/), "1250");
    await user.type(within(dlg).getByLabelText(/Number of runs/), "5");
    await user.click(within(dlg).getByRole("button", { name: /Launch \(real spend/ }));
    const alert = await within(dlg).findByRole("alert");
    expect(alert).toHaveTextContent("HTTP 422 confirmation_mismatch");
    expect(alert).toHaveTextContent(HOSTILE);
    expect(alert.querySelector("img")).toBeNull();
  });
});

describe("Nonce lifecycle and conflicts", () => {
  it("expires after the countdown and requires a new preview", async () => {
    const short = { ...previewScripted, expires_in_s: 1 };
    let previews = 0;
    const { user } = await previewSpec(short, { "/launch/preview": () => (previews++, { body: short }) });
    await user.click(screen.getByRole("button", { name: /Review and launch/ }));
    const dlg = screen.getByRole("dialog");
    await within(dlg).findByText(/confirmation expired/i, undefined, { timeout: 4000 });
    expect(within(dlg).getByRole("button", { name: "Launch" })).toBeDisabled();
    await user.click(within(dlg).getByRole("button", { name: "Preview again" }));
    await waitFor(() => expect(previews).toBe(2));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); // new preview shown inline, dialog closed
    await screen.findByText(/2\. Estimate/);
  });

  it("409 spec_changed burns the preview: message shown, launch disabled, Preview again offered", async () => {
    const { user } = await previewSpec(previewScripted, { "/launch": () => err(409, "spec_changed", "the spec changed since the preview; preview again") });
    await user.click(screen.getByRole("button", { name: /Review and launch/ }));
    const dlg = screen.getByRole("dialog");
    await user.click(within(dlg).getByRole("button", { name: "Launch" }));
    const alert = await within(dlg).findByRole("alert");
    expect(alert).toHaveTextContent("409 spec_changed");
    expect(alert).toHaveTextContent("the spec changed since the preview");
    expect(within(dlg).getByRole("button", { name: "Launch" })).toBeDisabled();
    expect(within(dlg).getByRole("button", { name: "Preview again" })).toBeInTheDocument();
  });

  it("409 run_active shows the server text and keeps the nonce usable", async () => {
    const { user } = await previewSpec(previewScripted, { "/launch": () => err(409, "run_active", "a run is active (pid 4242); one run at a time") });
    await user.click(screen.getByRole("button", { name: /Review and launch/ }));
    const dlg = screen.getByRole("dialog");
    await user.click(within(dlg).getByRole("button", { name: "Launch" }));
    expect(await within(dlg).findByRole("alert")).toHaveTextContent("a run is active (pid 4242)");
    expect(within(dlg).getByRole("button", { name: "Launch" })).toBeEnabled();
  });

  it("500 launch_failed shows the log tail as text", async () => {
    const { user } = await previewSpec(previewScripted, { "/launch": () => err(500, "launch_failed", "the CLI exited at once", { log_tail: `Traceback ${HOSTILE}` }) });
    await user.click(screen.getByRole("button", { name: /Review and launch/ }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Launch" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(`Traceback ${HOSTILE}`);
    expect(alert.querySelector("img")).toBeNull();
  });

  it("while a run is active: explains why, and the Launch button stays disabled", async () => {
    const { user } = await previewSpec(previewScripted, {}, active);
    expect(screen.getByText("Launch is not allowed while a run is active.")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "other-run-A-r00-abc" })[0]).toHaveAttribute("href", "/runs/other-run-A-r00-abc");
    await user.click(screen.getByRole("button", { name: /Review and launch/ }));
    const dlg = screen.getByRole("dialog");
    expect(within(dlg).getByRole("button", { name: "Launch" })).toBeDisabled();
    expect(within(dlg).getByText(/launch is not allowed until it ends/)).toBeInTheDocument();
  });

  it("a preview with blockers issues no nonce: nothing can be launched", async () => {
    const blocked = { ...previewScripted, blockers: ["a run folder already exists"], confirmation_nonce: null, launch_allowed_now: true };
    await previewSpec(blocked);
    expect(screen.getByText("a run folder already exists")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Review and launch/ })).toBeDisabled();
  });
});

describe("Control bar", () => {
  function bar(state: unknown) {
    mockFetch({ "/control/state": state });
    render(
      <MemoryRouter>
        <ControlBar />
      </MemoryRouter>,
    );
  }
  it("idle: says no run is active", async () => {
    bar(controlIdle);
    expect(await screen.findByText("No run is active.")).toBeInTheDocument();
  });
  it("active: link to the live page, explanation, launch log on demand (as text)", async () => {
    bar({ ...active, log_tail: `boot ${HOSTILE}` });
    const link = await screen.findByRole("link", { name: "other-run-A-r00-abc" });
    expect(link).toHaveAttribute("href", "/runs/other-run-A-r00-abc");
    expect(screen.getByText(/only one run can be managed at a time/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Launch log" }));
    expect(screen.getByLabelText("Launch log tail")).toHaveTextContent(`boot ${HOSTILE}`);
    expect(document.querySelector("img")).toBeNull();
  });
});

// ---------------- run actions ----------------

function detailWith(over: Partial<RunDetail["run"]>): RunDetail {
  return { ...(runScripted as unknown as RunDetail), run: { ...(runScripted.run as unknown as RunDetail["run"]), ...over } };
}

function renderActions(detail: RunDetail, table: Record<string, unknown | H> = {}, control: unknown = controlIdle) {
  const m = mockFetch({ "/control/state": control, [`/runs/${RUN_ID}/checkpoints`]: checkpoints, ...table });
  render(
    <DataVersionProvider>
      <MemoryRouter>
        <Routes>
          <Route path="*" element={<RunActions detail={detail} />} />
        </Routes>
      </MemoryRouter>
    </DataVersionProvider>,
  );
  return { m, user: userEvent.setup() };
}

const names = () => screen.getAllByRole("button").map((b) => b.textContent);

describe("Run actions: visibility by state", () => {
  it("live run: Stop and Kill only", async () => {
    renderActions(detailWith({ live: true, state: "running", end_epoch: null }));
    expect(names()).toEqual(["Stop…", "Kill…"]);
  });
  it("completed run: re-score and clean, no resume, no stop/kill", async () => {
    renderActions(detailWith({ state: "COMPLETED" }));
    expect(names()).toEqual(["Re-score…", "Clean…"]);
  });
  it.each(["FAILED", "INTERRUPTED", "KILLED", "BUDGET_EXHAUSTED"])("%s run: resume, re-score, clean", async (state) => {
    renderActions(detailWith({ state }));
    expect(names()).toEqual(["Resume…", "Re-score…", "Clean…"]);
  });
  it("run with no checkpoints cannot be resumed or scored", async () => {
    renderActions(detailWith({ state: "FAILED", checkpoints: 0 }));
    expect(names()).toEqual(["Clean…"]);
  });
  it("another run active: resume, score and clean are disabled with a reason", async () => {
    renderActions(detailWith({ state: "FAILED" }), {}, active);
    await waitFor(() => expect(screen.getByRole("button", { name: "Resume…" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Resume…" })).toHaveAttribute("title", expect.stringContaining("only one run"));
    expect(screen.getByRole("button", { name: "Re-score…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clean…" })).toBeDisabled();
  });
});

describe("Run actions: stop and kill", () => {
  const live = () => detailWith({ live: true, state: "running", end_epoch: null });

  it("stop explains the graceful interrupt and FAILED end state, and needs the dialog button", async () => {
    const { user, m } = renderActions(live(), { [`/runs/${RUN_ID}/stop`]: R({ signalled: "SIGINT", pid: 77, run_id: RUN_ID }) });
    await user.click(screen.getByRole("button", { name: "Stop…" }));
    const dlg = screen.getByRole("dialog", { name: "Stop this run?" });
    expect(dlg).toHaveTextContent("graceful interrupt");
    expect(dlg).toHaveTextContent("FAILED");
    expect(m.calls.some((c) => c.path.endsWith("/stop"))).toBe(false);
    await user.click(within(dlg).getByRole("button", { name: "Stop run" }));
    expect(await within(dlg).findByText(/SIGINT sent to pid 77/)).toBeInTheDocument();
    expect(m.calls.filter((c) => c.path.endsWith("/stop"))).toHaveLength(1);
  });

  it("stop 409 shows the server text", async () => {
    const { user } = renderActions(live(), { [`/runs/${RUN_ID}/stop`]: () => err(409, "stop_already_requested", "stop was already requested") });
    await user.click(screen.getByRole("button", { name: "Stop…" }));
    await user.click(screen.getByRole("button", { name: "Stop run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("stop was already requested");
  });

  it("kill requires typing the run id", async () => {
    const { user, m } = renderActions(live(), {
      [`/runs/${RUN_ID}/kill`]: R({ signalled: "SIGKILL", pid: 77, run_id: RUN_ID, clean: { finished: true, exit_code: 0, output_tail: `cleaned ${HOSTILE}` } }),
    });
    await user.click(screen.getByRole("button", { name: "Kill…" }));
    const dlg = screen.getByRole("dialog", { name: "Kill this run?" });
    const go = within(dlg).getByRole("button", { name: "Kill run" });
    expect(go).toBeDisabled();
    const input = within(dlg).getByRole("textbox");
    await user.type(input, RUN_ID.slice(0, -1));
    expect(go).toBeDisabled();
    await user.type(input, RUN_ID.slice(-1));
    expect(go).toBeEnabled();
    await user.type(input, "x");
    expect(go).toBeDisabled();
    await user.keyboard("{Backspace}");
    await user.click(go);
    expect(await within(dlg).findByText(/SIGKILL sent to pid 77/)).toBeInTheDocument();
    expect(within(dlg).getByText(`cleaned ${HOSTILE}`, { exact: false })).toBeInTheDocument();
    expect(dlg.querySelector("img")).toBeNull();
    expect(bodyOf(m.calls, `/runs/${RUN_ID}/kill`)).toEqual({ confirm: RUN_ID });
  });
});

describe("Run actions: resume", () => {
  const failed = () => detailWith({ state: "FAILED" });
  const rp = `/runs/${RUN_ID}/resume/preview`;
  const resumePreview = (over: object = {}, est: object = {}): PreviewResponse =>
    ({
      ...previewScripted,
      ...over,
      estimate: { ...previewScripted.estimate, kind: "resume", run_id: RUN_ID, from: "t2", remaining_checkpoints: 4, max_spend_usd: 1.0, run_ids: undefined, ...est },
    }) as unknown as PreviewResponse;

  it("scripted resume: pick checkpoint, preview, confirm, POST with from and nonce", async () => {
    const { user, m } = renderActions(failed(), {
      [rp]: resumePreview(),
      [`/runs/${RUN_ID}/resume`]: R({ started: true, manifest_seen: true, pid: 3, run_id: RUN_ID }),
    });
    await user.click(screen.getByRole("button", { name: "Resume…" }));
    const dlg = await screen.findByRole("dialog", { name: "Resume from a checkpoint" });
    const preview = within(dlg).getByRole("button", { name: "Preview resume" });
    expect(preview).toBeDisabled();
    await user.selectOptions(await within(dlg).findByLabelText("Resume from"), "2");
    await user.click(preview);
    expect(await within(dlg).findByText("Remaining checkpoints")).toBeInTheDocument();
    expect(bodyOf(m.calls, rp)).toEqual({ from: "t2" });
    await user.click(within(dlg).getByRole("button", { name: "Resume" }));
    expect(await within(dlg).findByText("Resume started.")).toBeInTheDocument();
    expect(bodyOf(m.calls, `/runs/${RUN_ID}/resume`)).toEqual({ from: "t2", nonce: previewScripted.confirmation_nonce });
  });

  it("real-spend resume needs typed figures", async () => {
    const real = resumePreview(
      { confirmation: { required: true, fields: { confirm_usd: 250, confirm_runs: 1 }, message: "type it" }, confirmation_nonce: "N2" },
      { real_spend: true, runtime: "claude_code", model: "claude-opus-5-5", max_spend_usd: 250, spend_reasons: ["agent runtime claude_code uses the Claude subscription"] },
    );
    const { user, m } = renderActions(failed(), { [rp]: real, [`/runs/${RUN_ID}/resume`]: R({ started: true, manifest_seen: true, pid: 3, run_id: RUN_ID }) });
    await user.click(screen.getByRole("button", { name: "Resume…" }));
    const dlg = await screen.findByRole("dialog");
    await user.selectOptions(await within(dlg).findByLabelText("Resume from"), "3");
    await user.click(within(dlg).getByRole("button", { name: "Preview resume" }));
    expect(await within(dlg).findByText("REAL SPEND")).toBeInTheDocument();
    const go = within(dlg).getByRole("button", { name: /Resume \(real spend/ });
    expect(go).toBeDisabled();
    await user.type(within(dlg).getByLabelText(/Maximum spend in USD/), "250");
    expect(go).toBeDisabled();
    await user.type(within(dlg).getByLabelText(/Number of runs/), "2");
    expect(go).toBeDisabled();
    await user.clear(within(dlg).getByLabelText(/Number of runs/));
    await user.type(within(dlg).getByLabelText(/Number of runs/), "1");
    expect(go).toBeEnabled();
    await user.click(go);
    await within(dlg).findByText("Resume started.");
    expect(bodyOf(m.calls, `/runs/${RUN_ID}/resume`)).toEqual({ from: "t3", nonce: "N2", confirm_usd: 250, confirm_runs: 1 });
  });

  it("shows the server's error when the preview is refused", async () => {
    const { user } = renderActions(failed(), { [rp]: () => err(422, "spec_changed_since_run", `spec hash differs ${HOSTILE}`) });
    await user.click(screen.getByRole("button", { name: "Resume…" }));
    const dlg = await screen.findByRole("dialog");
    await user.selectOptions(await within(dlg).findByLabelText("Resume from"), "1");
    await user.click(within(dlg).getByRole("button", { name: "Preview resume" }));
    const alert = await within(dlg).findByRole("alert");
    expect(alert).toHaveTextContent("spec hash differs");
    expect(alert.querySelector("img")).toBeNull();
  });
});

describe("Run actions: re-score and clean", () => {
  it("re-score: explains the judge rule; sends the checkpoint", async () => {
    const { user, m } = renderActions(detailWith({ state: "COMPLETED" }), { [`/runs/${RUN_ID}/score`]: R({ started: true, finished: true, exit_code: 0, output_tail: "scored" }, 202) });
    await user.click(screen.getByRole("button", { name: "Re-score…" }));
    const dlg = screen.getByRole("dialog", { name: "Re-score this run" });
    expect(dlg).toHaveTextContent("judge_spends");
    await user.selectOptions(await within(dlg).findByLabelText("Checkpoint"), "4");
    await user.click(within(dlg).getByRole("button", { name: "Re-score" }));
    expect(await within(dlg).findByText("scored")).toBeInTheDocument();
    expect(bodyOf(m.calls, `/runs/${RUN_ID}/score`)).toEqual({ checkpoint: 4 });
  });

  it("re-score 409 judge_spends is shown clearly", async () => {
    const { user } = renderActions(detailWith({ state: "COMPLETED" }), {
      [`/runs/${RUN_ID}/score`]: () => err(409, "judge_spends", "this run's judge is claude_code and would spend; score it from the terminal"),
    });
    await user.click(screen.getByRole("button", { name: "Re-score…" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Re-score" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("409 judge_spends");
    expect(alert).toHaveTextContent("score it from the terminal");
  });

  it("clean: global explanation, POST, output shown", async () => {
    const { user, m } = renderActions(detailWith({ state: "FAILED" }), { "/clean": R({ finished: true, exit_code: 0, output_tail: "nothing to clean" }) });
    await user.click(screen.getByRole("button", { name: "Clean…" }));
    const dlg = screen.getByRole("dialog");
    expect(dlg).toHaveTextContent("global");
    expect(m.calls.some((c) => c.path === "/clean")).toBe(false);
    await user.click(within(dlg).getByRole("button", { name: "Run clean" }));
    expect(await within(dlg).findByText("nothing to clean")).toBeInTheDocument();
  });
});
