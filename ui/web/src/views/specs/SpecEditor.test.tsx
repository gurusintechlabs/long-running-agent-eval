import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initToken } from "../../api";
import detailFx from "../../test/fixtures/spec_minidb_v3.json";
import schemaFx from "../../test/fixtures/specs_schema.json";
import { mockFetch, renderRoute, resetAuth, type Handler } from "../../test/helpers";
import { setAt, splitPath } from "./formLogic";
import { SpecEditorPage } from "./SpecEditor";

type Body = Record<string, unknown>;
const body = (init?: RequestInit): Body => JSON.parse(String(init?.body ?? "{}"));

const draftDetail = { ...detailFx, name: "mine", source: "draft", editable: true, path: "spec/drafts/mine.yaml" };
const okValidation = detailFx.validation;

function validateSpy(respond?: (b: Body) => { status?: number; body: unknown }) {
  const seen: Body[] = [];
  const h: Handler = (init) => {
    const b = body(init);
    seen.push(b);
    return respond ? respond(b) : { body: okValidation };
  };
  return { h, seen };
}

function setup(opts: { route?: string; validate?: Handler; extra?: Record<string, unknown> } = {}) {
  const v = validateSpy();
  const table = {
    "/specs/schema": schemaFx,
    "/specs/minidb-v3?source=example": detailFx,
    "/specs/mine?source=draft": draftDetail,
    "/specs/validate": opts.validate ?? v.h,
    ...opts.extra,
  };
  const net = mockFetch(table);
  const ui = renderRoute(<SpecEditorPage />, opts.route ?? "/specs/minidb-v3?source=example", "/specs/:name");
  return { net, ui, seen: v.seen };
}

beforeEach(() => {
  resetAuth();
  initToken();
});
afterEach(() => vi.restoreAllMocks());

const input = (path: string) => document.getElementById(`i:${path}`) as HTMLInputElement;

describe("loading", () => {
  it("shows the example with its validation result, hash and run ids", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: "minidb-v3" })).toBeInTheDocument();
    expect(screen.getByText(/This is an example/)).toBeInTheDocument();
    expect(await screen.findByText("Valid: what this spec will produce")).toBeInTheDocument();
    expect(screen.getByText(detailFx.spec_hash!)).toBeInTheDocument();
    expect(screen.getByText(detailFx.run_ids[0])).toBeInTheDocument();
    expect(screen.getAllByText(/spends real money/i).length).toBeGreaterThan(0); // warning list
    expect(input("run.duration_min").value).toBe("360");
    expect(input("agent.model").value).toBe("claude-opus-5-5");
  });

  it("reports a missing spec", async () => {
    setup({ route: "/specs/ghost?source=draft" });
    expect(await screen.findByText("No such spec")).toBeInTheDocument();
  });
});

describe("round trip: load -> edit -> validate payload", () => {
  it("an untouched form sends exactly the data the server returned", async () => {
    const { seen } = setup();
    await screen.findByText("Valid: what this spec will produce");
    await userEvent.click(screen.getByRole("button", { name: "Validate" }));
    await waitFor(() => expect(seen.length).toBe(1));
    expect(seen[0]).toEqual({ data: detailFx.data });
    expect(screen.queryByText("unsaved changes")).not.toBeInTheDocument();
  });

  it("an edit changes only that field in the debounced validate payload and marks the form dirty", async () => {
    const { seen } = setup();
    await screen.findByText("Valid: what this spec will produce");
    const dur = input("run.duration_min");
    await userEvent.clear(dur);
    await userEvent.type(dur, "120");
    expect(await screen.findByText("unsaved changes")).toBeInTheDocument();
    await waitFor(() => expect(seen.length).toBeGreaterThan(0), { timeout: 2000 });
    const last = seen[seen.length - 1];
    expect(last).toEqual({ data: setAt(detailFx.data as Record<string, unknown>, splitPath("run.duration_min"), 120) });
    // exactly one key differs
    const before = detailFx.data as { run: Record<string, unknown> };
    const after = (last.data as { run: Record<string, unknown> }).run;
    expect(Object.keys(after).filter((k) => JSON.stringify(after[k]) !== JSON.stringify(before.run[k]))).toEqual(["duration_min"]);
  });

  it("undoing the edit makes the form clean again", async () => {
    setup();
    await screen.findByText("Valid: what this spec will produce");
    const dur = input("run.duration_min");
    await userEvent.type(dur, "0");
    expect(await screen.findByText("unsaved changes")).toBeInTheDocument();
    await userEvent.type(dur, "{Backspace}");
    await waitFor(() => expect(screen.queryByText("unsaved changes")).not.toBeInTheDocument());
  });
});

describe("live validation display", () => {
  const bad = {
    valid: false,
    errors: [
      { path: "run.checkpoint_interval_min", group: "run", type: "value_error", message: "checkpoint_interval_min must divide duration_min" },
      { path: "task.honey.0.where", type: "literal_error", message: "Input should be 'workspace' or 'outside'" },
      { path: "", type: "loader", message: "something about the whole spec" },
    ],
    warnings: [{ path: "budget.per_run_usd", level: "warning", message: "High per-run cap: $250." }],
    spec_hash: null,
    run_ids: [],
    summary: {},
  };

  it("shows errors inline, in a summary, and jumps to the field from the summary", async () => {
    setup({ validate: () => ({ body: bad }) });
    await screen.findByRole("heading", { name: "minidb-v3" });
    await userEvent.type(input("run.duration_min"), "0"); // triggers a validate
    expect(await screen.findByText("3 problems to fix")).toBeInTheDocument();
    expect(screen.getByText("3 errors")).toBeInTheDocument();
    const field = document.getElementById("f:run.checkpoint_interval_min")!;
    expect(within(field).getByText("checkpoint_interval_min must divide duration_min")).toBeInTheDocument();
    // the honey row error is inside the collapsed Advanced group: it opens by itself
    expect(within(document.getElementById("f:task.honey.0.where")!).getByText(/Input should be/)).toBeInTheDocument();
    expect(screen.getByText("(whole spec)")).toBeInTheDocument();
    // warnings show next to the field
    expect(within(document.getElementById("f:budget.per_run_usd")!).getByText("High per-run cap: $250.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /run\.checkpoint_interval_min/ }));
    await waitFor(() => expect(document.activeElement).toBe(input("run.checkpoint_interval_min")));
  });

  it("an error inside a collapsed section opens it from the summary", async () => {
    const bad2 = { ...bad, errors: [{ path: "scoring.behavior.stall_min_s", type: "value_error", message: "too small" }], warnings: [] };
    setup({ validate: () => ({ body: bad2 }) });
    await screen.findByRole("heading", { name: "minidb-v3" });
    await userEvent.type(input("run.duration_min"), "0");
    const item = await screen.findByRole("button", { name: /scoring\.behavior\.stall_min_s/ });
    await userEvent.click(item);
    await waitFor(() => expect(document.activeElement).toBe(input("scoring.behavior.stall_min_s")));
  });

  it("shows a failed validation request without losing the form", async () => {
    setup({ validate: () => ({ status: 500, body: { detail: "boom" } }) });
    await screen.findByRole("heading", { name: "minidb-v3" });
    await userEvent.type(input("run.duration_min"), "0");
    expect(await screen.findByText(/Validation request failed: boom/)).toBeInTheDocument();
    expect(input("run.duration_min").value).toBe("3600");
  });
});

describe("unsaved changes guard", () => {
  it("asks before following an in-app link when the form is dirty, and stays when declined", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    setup();
    await screen.findByText("Valid: what this spec will produce");
    await userEvent.type(input("run.duration_min"), "0");
    await screen.findByText("unsaved changes");
    await userEvent.click(screen.getByRole("link", { name: "← Specs" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("elsewhere")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "minidb-v3" })).toBeInTheDocument();
  });

  it("leaves when the user agrees", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    setup();
    await screen.findByText("Valid: what this spec will produce");
    await userEvent.type(input("run.duration_min"), "0");
    await userEvent.click(screen.getByRole("link", { name: "← Specs" }));
    expect(await screen.findByText("elsewhere")).toBeInTheDocument();
  });

  it("does not ask when nothing changed", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    setup();
    await screen.findByText("Valid: what this spec will produce");
    await userEvent.click(screen.getByRole("link", { name: "← Specs" }));
    expect(confirm).not.toHaveBeenCalled();
    expect(await screen.findByText("elsewhere")).toBeInTheDocument();
  });

  it("registers a beforeunload handler only while dirty", async () => {
    const add = vi.spyOn(window, "addEventListener");
    setup();
    await screen.findByText("Valid: what this spec will produce");
    expect(add.mock.calls.some((c) => c[0] === "beforeunload")).toBe(false);
    await userEvent.type(input("run.duration_min"), "0");
    await waitFor(() => expect(add.mock.calls.some((c) => c[0] === "beforeunload")).toBe(true));
  });

  it("keeps unsaved edits in the session and restores them when the editor is opened again", async () => {
    const first = setup();
    await screen.findByText("Valid: what this spec will produce");
    await userEvent.type(input("run.duration_min"), "0");
    await screen.findByText("unsaved changes");
    first.ui.unmount();
    setup();
    expect(await screen.findByText(/Restored unsaved edits/)).toBeInTheDocument();
    expect(input("run.duration_min").value).toBe("3600");
    await userEvent.click(screen.getByRole("button", { name: "Discard them" }));
    expect(input("run.duration_min").value).toBe("360");
  });
});

describe("saving", () => {
  it("saves an edited example as a new draft under the typed name", async () => {
    const saveBodies: Body[] = [];
    setup({
      extra: {
        "/specs/save": (init: RequestInit | undefined) => {
          saveBodies.push(body(init));
          return { body: { ...okValidation, saved: true, name: "mine", source: "draft", path: "spec/drafts/mine.yaml" } };
        },
      },
    });
    await screen.findByText("Valid: what this spec will produce");
    const name = screen.getByPlaceholderText(/draft name/);
    await userEvent.clear(name);
    await userEvent.type(name, "Bad Name");
    expect(await screen.findByText(/Use lowercase letters/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save as draft" })).toBeDisabled();
    await userEvent.clear(name);
    await userEvent.type(name, "mine");
    await userEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    await waitFor(() => expect(saveBodies).toHaveLength(1));
    expect(saveBodies[0]).toEqual({ name: "mine", data: detailFx.data, overwrite: false });
    // lands on the saved draft with a way into Launch
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const launch = await screen.findByRole("link", { name: /Launch this draft/ });
    expect(launch).toHaveAttribute("href", "/launch?spec=mine");
  });

  it("asks before overwriting when the name is taken (409), then retries with overwrite", async () => {
    const saves: Body[] = [];
    setup({
      extra: {
        "/specs/save": (init: RequestInit | undefined) => {
          const b = body(init);
          saves.push(b);
          return b.overwrite
            ? { body: { ...okValidation, saved: true, name: "mine", source: "draft", path: "spec/drafts/mine.yaml" } }
            : { status: 409, body: { detail: "draft exists" } };
        },
      },
    });
    await screen.findByText("Valid: what this spec will produce");
    const name = screen.getByPlaceholderText(/draft name/);
    await userEvent.clear(name);
    await userEvent.type(name, "mine");
    await userEvent.click(screen.getByRole("button", { name: "Save as draft" }));
    const dialog = await screen.findByRole("dialog", { name: "A draft with this name exists" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Overwrite" }));
    await waitFor(() => expect(saves.map((s) => s.overwrite)).toEqual([false, true]));
  });

  it("saving an existing draft needs an overwrite confirmation and shows the server's errors on 422", async () => {
    const bad = { saved: false, valid: false, errors: [{ path: "experiment_id", message: "nope", type: "value_error" }], warnings: [] };
    const saves: Body[] = [];
    setup({
      route: "/specs/mine?source=draft",
      extra: {
        "/specs/save": (init: RequestInit | undefined) => {
          saves.push(body(init));
          return { status: 422, body: bad };
        },
      },
    });
    await screen.findByText("Valid: what this spec will produce");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled(); // clean
    await userEvent.type(input("experiment_id"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const dialog = await screen.findByRole("dialog", { name: "Overwrite this draft?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Overwrite" }));
    await waitFor(() => expect(saves).toHaveLength(1));
    expect(saves[0].overwrite).toBe(true);
    expect(await screen.findByText("Not saved: the spec has errors.")).toBeInTheDocument();
    expect(within(document.getElementById("f:experiment_id")!).getByText("nope")).toBeInTheDocument();
  });

  it("Ctrl+S opens the same overwrite confirmation", async () => {
    setup({ route: "/specs/mine?source=draft" });
    await screen.findByText("Valid: what this spec will produce");
    await userEvent.type(input("experiment_id"), "x");
    fireEvent.keyDown(document, { key: "s", ctrlKey: true });
    expect(await screen.findByRole("dialog", { name: "Overwrite this draft?" })).toBeInTheDocument();
  });

  it("Launch link points at the saved draft only when the form is clean and valid", async () => {
    setup({ route: "/specs/mine?source=draft" });
    const link = await screen.findByRole("link", { name: /Launch this draft/ });
    expect(link).toHaveAttribute("href", "/launch?spec=mine");
    await userEvent.type(input("experiment_id"), "x");
    await waitFor(() => expect(screen.queryByRole("link", { name: /Launch this draft/ })).not.toBeInTheDocument());
  });
});

describe("YAML tab", () => {
  it("previews generated YAML, edits it through the same validate endpoint and round-trips back to the form", async () => {
    const { seen } = setup();
    await screen.findByText("Valid: what this spec will produce");
    await userEvent.click(screen.getByRole("tab", { name: "YAML" }));
    const pre = await screen.findByLabelText("Generated YAML");
    await waitFor(() => expect(pre.textContent).toContain("experiment_id: minidb-v3-l4"));

    await userEvent.click(screen.getByRole("button", { name: "Edit as YAML" }));
    const area = (await screen.findByLabelText("Spec YAML")) as HTMLTextAreaElement;
    expect(area.value).toContain("experiment_id: minidb-v3-l4");
    fireEvent.change(area, { target: { value: area.value.replace("minidb-v3-l4", "edited-in-yaml") } });
    await waitFor(() => expect(seen.some((b) => typeof b.yaml === "string" && String(b.yaml).includes("edited-in-yaml"))).toBe(true), { timeout: 2000 });
    expect(seen.every((b) => ("yaml" in b) !== ("data" in b))).toBe(true); // exactly one of data / yaml

    await userEvent.click(screen.getByRole("tab", { name: "Form" }));
    expect(input("experiment_id").value).toBe("edited-in-yaml");
    expect(screen.getByText("unsaved changes")).toBeInTheDocument();
  });

  it("shows a YAML syntax error and keeps the last good data in the form", async () => {
    const { seen } = setup();
    await screen.findByText("Valid: what this spec will produce");
    await userEvent.click(screen.getByRole("tab", { name: "YAML" }));
    await userEvent.click(await screen.findByRole("button", { name: "Edit as YAML" }));
    const area = (await screen.findByLabelText("Spec YAML")) as HTMLTextAreaElement;
    const before = seen.length;
    fireEvent.change(area, { target: { value: "a: [unclosed\nb: : :" } });
    expect(await screen.findByText(/YAML error:/)).toBeInTheDocument();
    expect(seen.length).toBe(before); // nothing is sent to the server for text that does not parse
    await userEvent.click(screen.getByRole("tab", { name: "Form" }));
    expect(input("experiment_id").value).toBe("minidb-v3-l4");
  });
});

describe("hostile strings", () => {
  it("renders hostile server messages, names and values as text", async () => {
    const evil = "<img src=x onerror=\"window.__pwned=1\">";
    const bad = {
      valid: false,
      errors: [{ path: "experiment_id", message: evil, type: "value_error" }],
      warnings: [{ path: "agent.runtime", message: evil, level: "warning" }],
      spec_hash: null,
      run_ids: [],
      summary: {},
    };
    setup({ validate: () => ({ body: bad }) });
    await screen.findByRole("heading", { name: "minidb-v3" });
    await userEvent.type(input("experiment_id"), "z");
    expect((await screen.findAllByText(evil)).length).toBeGreaterThan(1);
    expect(document.querySelector("img")).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });

  it("a hostile spec name is shown as text", async () => {
    const evilName = "<script>window.__pwned=2</script>";
    const enc = encodeURIComponent(evilName);
    setup({ extra: { [`/specs/${enc}?source=draft`]: { ...draftDetail, name: evilName } }, route: `/specs/${enc}?source=draft` });
    expect(await screen.findByRole("heading", { name: evilName })).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });
});
