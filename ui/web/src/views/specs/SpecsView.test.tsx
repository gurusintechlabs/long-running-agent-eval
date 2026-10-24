import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { initToken, type SpecListEntry } from "../../api";
import listFx from "../../test/fixtures/specs_list.json";
import { mockFetch, renderRoute, resetAuth, type Handler } from "../../test/helpers";
import { SpecsView } from "./SpecsView";

const examples = listFx.specs as SpecListEntry[];
const draft: SpecListEntry = { ...examples[0], name: "mine", source: "draft", editable: true, path: "spec/drafts/mine.yaml" };
const broken: SpecListEntry = {
  ...examples[1],
  name: "broken",
  source: "draft",
  editable: true,
  valid: false,
  spec_hash: null,
  errors: [{ path: "run.duration_min", message: "must be positive", type: "value_error" }],
};
const list = (specs: SpecListEntry[]) => ({ ...listFx, specs });

beforeEach(() => {
  resetAuth();
  initToken();
});

const render = (table: Record<string, unknown | Handler>) => {
  const net = mockFetch(table);
  renderRoute(<SpecsView />, "/specs", "/specs");
  return net;
};

describe("Specs list", () => {
  it("lists examples and drafts with validity, short hash, runtime/model and a real-spend marker", async () => {
    render({ "/specs": list([draft, broken, ...examples]) });
    expect(await screen.findByText("Drafts (2)")).toBeInTheDocument();
    expect(screen.getByText("Examples (12)")).toBeInTheDocument();
    const row = screen.getByRole("link", { name: "minidb-v3" }).closest("tr")!;
    expect(within(row).getByText("valid")).toBeInTheDocument();
    expect(within(row).getByText("real spend")).toBeInTheDocument();
    expect(within(row).getByText(examples.find((e) => e.name === "minidb-v3")!.spec_hash!.slice(0, 12))).toBeInTheDocument();
    // scripted examples are not marked
    const scripted = screen.getByRole("link", { name: "pilot-scripted" }).closest("tr")!;
    expect(within(scripted).queryByText("real spend")).not.toBeInTheDocument();
    // invalid drafts show why
    const bad = screen.getByRole("link", { name: "broken" }).closest("tr")!;
    expect(within(bad).getByText("invalid")).toBeInTheDocument();
    expect(within(bad).getByText(/must be positive/)).toBeInTheDocument();
    // actions differ: examples are read-only
    expect(within(row).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Duplicate to draft" })).toBeInTheDocument();
    const mineRow = screen.getByRole("link", { name: "mine" }).closest("tr")!;
    expect(within(mineRow).getByRole("link", { name: "Edit" })).toHaveAttribute("href", "/specs/mine?source=draft");
    expect(within(mineRow).getByRole("link", { name: "Launch" })).toHaveAttribute("href", "/launch?spec=mine");
    expect(within(bad).queryByRole("link", { name: "Launch" })).not.toBeInTheDocument(); // invalid: cannot launch
  });

  it("filters by search text", async () => {
    render({ "/specs": list([draft, ...examples]) });
    await screen.findByText("Drafts (1)");
    await userEvent.type(screen.getByRole("searchbox"), "minidb-v3");
    expect(screen.getByText(/Examples \([1-9]\d?\)/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "pilot" })).not.toBeInTheDocument();
    expect(screen.getByText("No draft matches")).toBeInTheDocument();
  });

  it("shows an empty-drafts hint", async () => {
    render({ "/specs": list(examples) });
    expect(await screen.findByText("No drafts yet")).toBeInTheDocument();
  });

  it("duplicates an example into a draft after naming it, then opens the editor", async () => {
    const bodies: Record<string, unknown>[] = [];
    render({
      "/specs": list(examples),
      "/specs/pilot/duplicate": (init: RequestInit | undefined) => {
        bodies.push(JSON.parse(String(init?.body)));
        return { body: { saved: true, name: "pilot-mine", source: "draft", path: "spec/drafts/pilot-mine.yaml" } };
      },
    });
    const row = (await screen.findByRole("link", { name: "pilot" })).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Duplicate to draft" }));
    const dlg = screen.getByRole("dialog", { name: /Duplicate “pilot”/ });
    const name = within(dlg).getByRole("textbox");
    expect(name).toHaveValue("pilot-copy");
    await userEvent.clear(name);
    await userEvent.type(name, "Bad Name");
    expect(within(dlg).getByText(/Use lowercase letters/)).toBeInTheDocument();
    expect(within(dlg).getByRole("button", { name: "Duplicate" })).toBeDisabled();
    await userEvent.clear(name);
    await userEvent.type(name, "pilot-mine");
    await userEvent.click(within(dlg).getByRole("button", { name: "Duplicate" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ new_name: "pilot-mine", source: "example", overwrite: false });
    expect(await screen.findByText("elsewhere")).toBeInTheDocument(); // navigated to the editor route
  });

  it("offers an explicit overwrite when the draft name is taken (409)", async () => {
    const seen: boolean[] = [];
    render({
      "/specs": list([draft, ...examples]),
      "/specs/pilot/duplicate": (init: RequestInit | undefined) => {
        const b = JSON.parse(String(init?.body));
        seen.push(b.overwrite);
        return b.overwrite ? { body: { saved: true, name: b.new_name } } : { status: 409, body: { detail: "exists" } };
      },
    });
    const row = (await screen.findByRole("link", { name: "pilot" })).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Duplicate to draft" }));
    const dlg = screen.getByRole("dialog");
    const name = within(dlg).getByRole("textbox");
    await userEvent.clear(name);
    await userEvent.type(name, "mine");
    await userEvent.click(within(dlg).getByRole("button", { name: "Duplicate" }));
    expect(await within(dlg).findByText(/already exists/)).toBeInTheDocument();
    await userEvent.click(within(dlg).getByRole("button", { name: "Overwrite and duplicate" }));
    await waitFor(() => expect(seen).toEqual([false, true]));
  });

  it("creates a draft from a chosen example (New from example)", async () => {
    const calls: string[] = [];
    render({
      "/specs": list(examples),
      "/specs/dryrun/duplicate": (init: RequestInit | undefined) => {
        calls.push(String(init?.body));
        return { body: { saved: true, name: "dryrun-copy" } };
      },
    });
    await screen.findByText("Examples (12)");
    await userEvent.click(screen.getByRole("button", { name: "New from example…" }));
    const dlg = screen.getByRole("dialog");
    await userEvent.selectOptions(within(dlg).getByRole("combobox"), "dryrun");
    expect(within(dlg).getByRole("textbox")).toHaveValue("dryrun-copy");
    await userEvent.click(within(dlg).getByRole("button", { name: "Create draft" }));
    await waitFor(() => expect(calls).toHaveLength(1));
  });

  it("deletes a draft only after confirmation and then reloads the list", async () => {
    let deleted = false;
    const net = render({
      "/specs": (() => ({ body: list(deleted ? examples : [draft, ...examples]) })) as Handler,
      "/specs/mine": (init: RequestInit | undefined) => {
        expect(init?.method).toBe("DELETE");
        deleted = true;
        return { body: { deleted: true } };
      },
    });
    const row = (await screen.findByRole("link", { name: "mine" })).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Delete" }));
    expect(net.calls.some((c) => c.init?.method === "DELETE")).toBe(false); // nothing yet
    await userEvent.click(screen.getByRole("button", { name: "Delete draft" }));
    await waitFor(() => expect(screen.queryByRole("link", { name: "mine" })).not.toBeInTheDocument());
    expect(screen.getByText("No drafts yet")).toBeInTheDocument();
  });

  it("cancel leaves the draft alone", async () => {
    const net = render({ "/specs": list([draft, ...examples]) });
    const row = (await screen.findByRole("link", { name: "mine" })).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Delete" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(net.calls.some((c) => c.init?.method === "DELETE")).toBe(false);
  });

  it("renders hostile spec names, experiment ids and errors as text", async () => {
    const evil = "<img src=x onerror=alert(1)>";
    const e1: SpecListEntry = { ...draft, name: evil, experiment_id: evil, valid: false, spec_hash: null, errors: [{ path: evil, message: evil }] };
    render({ "/specs": list([e1]) });
    expect((await screen.findAllByText(evil)).length).toBeGreaterThan(1);
    expect(document.querySelector("img")).toBeNull();
    // the link target is encoded, not interpolated
    expect(screen.getAllByRole("link", { name: evil })[0].getAttribute("href")).toBe(`/specs/${encodeURIComponent(evil)}?source=draft`);
  });

  it("shows an error state with retry when the list cannot be loaded", async () => {
    render({});
    expect(await screen.findByText("Cannot list specs")).toBeInTheDocument();
  });
});
