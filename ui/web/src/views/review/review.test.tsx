import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { initToken, type ReviewDecisionRecord, type ReviewItem } from "../../api";
import queueFx from "../../test/fixtures/review_queue.json";
import runsFx from "../../test/fixtures/review_runs.json";
import { mockFetch, renderRoute, resetAuth, type Handler } from "../../test/helpers";
import { applyDecisions, countItems, filterItems, DEFAULT_FILTERS, transcriptHref } from "./reviewLogic";
import { ReviewView } from "./ReviewView";

const RUN = "minidb-v3-pilot-haiku-A-r00-f47fe80e";
const items = queueFx.items as unknown as ReviewItem[];

beforeEach(() => {
  resetAuth();
  initToken();
});

function queuePath(run = RUN) {
  return `/review/queue?run_id=${encodeURIComponent(run)}&status=all&limit=500`;
}

type Decisions = { run_id: string; item_id: string; decision: string; note?: string };

function setup(opts: { items?: ReviewItem[]; decide?: Handler; batch?: Handler; extra?: Record<string, unknown> } = {}) {
  const list = opts.items ?? items;
  const decisions: Decisions[] = [];
  const batches: { run_id: string; decisions: { item_id: string; decision: string; note?: string }[] }[] = [];
  const table: Record<string, unknown | Handler> = {
    [queuePath()]: { items: list, total: list.length, offset: 0, counts: countItems(list) },
    "/review/runs": runsFx,
    "/review/decision": (init: RequestInit | undefined) => {
      const b = JSON.parse(String(init?.body)) as Decisions;
      decisions.push(b);
      if (opts.decide) return opts.decide(init);
      const rec: ReviewDecisionRecord = { ts: "2026-10-24T10:00:00.000Z", run_id: b.run_id, item_id: b.item_id, decision: b.decision as never, note: b.note ?? null, reviewer: "tester" };
      return { body: { ok: true, decision: rec } };
    },
    "/review/decisions": (init: RequestInit | undefined) => {
      const b = JSON.parse(String(init?.body)) as (typeof batches)[number];
      batches.push(b);
      if (opts.batch) return opts.batch(init);
      const recs = b.decisions.map((d) => ({ ts: "2026-10-24T10:00:01.000Z", run_id: b.run_id, item_id: d.item_id, decision: d.decision, note: d.note ?? null, reviewer: "tester" }));
      return { body: { ok: true, appended: recs.length, decisions: recs } };
    },
    ...opts.extra,
  };
  const net = mockFetch(table);
  const ui = renderRoute(<ReviewView />, `/review/${RUN}`, "/review/:runId");
  return { net, ui, decisions, batches };
}

const cards = () => screen.getAllByRole("listitem").filter((li) => li.id.startsWith("item-"));
const selected = () => document.querySelector<HTMLElement>("[aria-current='true']")!;

describe("review logic", () => {
  it("filters by status, kind, group and detector and counts by status", () => {
    expect(filterItems(items, DEFAULT_FILTERS)).toHaveLength(items.length);
    const hazards = filterItems(items, { ...DEFAULT_FILTERS, kind: "hazard" });
    expect(hazards.every((i) => i.kind === "hazard")).toBe(true);
    const g = items.find((i) => i.kind === "behavior")!;
    expect(filterItems(items, { ...DEFAULT_FILTERS, group: g.group, name: g.name }).every((i) => i.group === g.group && i.name === g.name)).toBe(true);
    expect(filterItems(items, { ...DEFAULT_FILTERS, status: "decided" })).toHaveLength(0);
  });

  it("latest decision wins and the history count grows (append-only)", () => {
    const id = items[0].item_id;
    const rec = (d: "confirm" | "reject", ts: string): ReviewDecisionRecord => ({ ts, run_id: RUN, item_id: id, decision: d, note: null, reviewer: null });
    const a = applyDecisions(items, [rec("confirm", "1")]);
    const b = applyDecisions(a, [rec("reject", "2")]);
    expect(b[0].status).toBe("reject");
    expect(b[0].history_count).toBe(2);
    expect(countItems(b).reject).toBe(1);
    expect(items[0].status).toBe("pending"); // inputs untouched
    expect(applyDecisions(items, [rec("confirm", "1"), rec("reject", "2")])[0].history_count).toBe(2);
  });

  it("builds the transcript link from the cursor", () => {
    const href = transcriptHref({ ...items[0], run_id: "r/1", k: 3, t_s: 9.5, context: { cursor: { k: 4, t_s: 12.3456789 } } });
    expect(href).toBe("/runs/r%2F1?tab=transcript&t_s=12.346&k=4");
    expect(transcriptHref({ ...items[0], k: null, t_s: null, context: undefined })).toBe(`/runs/${RUN}?tab=transcript`);
  });
});

describe("queue view", () => {
  it("shows counters, cards with evidence, rule/judge tag, time and a transcript link", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: RUN })).toBeInTheDocument();
    expect(screen.getByText(`${items.length} pending`)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: `0 of ${items.length} decided` })).toBeInTheDocument();
    expect(cards()).toHaveLength(items.length);
    const first = cards()[0];
    expect(within(first).getByText(items[0].evidence!.slice(0, 40), { exact: false })).toBeInTheDocument();
    const link = within(first).getByRole("link", { name: /Transcript/ });
    expect(link.getAttribute("href")).toMatch(/^\/runs\/.+\?tab=transcript&t_s=\d/);
    expect(selected()).toBe(first);
  });

  it("shows draft labels and notes when the server supplies them", async () => {
    const withDraft = items.map((i, n) => (n === 2 ? { ...i, proposed_label: "reject" as const, draft_note: "known false positive" } : i));
    setup({ items: withDraft });
    await screen.findByRole("heading", { name: RUN });
    expect(screen.getByText("draft label: reject")).toBeInTheDocument();
    expect(screen.getByText("known false positive")).toBeInTheDocument();
  });

  it("filters by kind and group, with the detector list following the group", async () => {
    setup();
    await screen.findByRole("heading", { name: RUN });
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "hazard");
    expect(cards().every((c) => within(c).getByText("hazard"))).toBe(true);
    expect(cards().length).toBe(items.filter((i) => i.kind === "hazard").length);
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "");
    const g = items.find((i) => i.kind === "behavior")!;
    await userEvent.selectOptions(screen.getByLabelText("Group"), g.group);
    const detector = screen.getByLabelText("Detector");
    const opts = within(detector).getAllByRole("option").map((o) => o.textContent);
    expect(opts.some((o) => o?.startsWith(g.name))).toBe(true);
    expect(opts.length).toBeLessThan(items.length + 1);
  });

  it("keyboard: j/k move, c/r/u decide and advance, note via n is sent and cleared", async () => {
    const { decisions } = setup();
    await screen.findByRole("heading", { name: RUN });
    const ids = cards().map((c) => c.id.slice(5));
    expect(selected().id).toBe(`item-${ids[0]}`);

    await userEvent.keyboard("j");
    expect(selected().id).toBe(`item-${ids[1]}`);
    await userEvent.keyboard("k");
    expect(selected().id).toBe(`item-${ids[0]}`);
    await userEvent.keyboard("k"); // stays at the top
    expect(selected().id).toBe(`item-${ids[0]}`);

    await userEvent.keyboard("c");
    await waitFor(() => expect(decisions).toHaveLength(1));
    expect(decisions[0]).toEqual({ run_id: RUN, item_id: ids[0], decision: "confirm" });
    // the decided item left the Pending list and the cursor is on the next one
    await waitFor(() => expect(document.getElementById(`item-${ids[0]}`)).toBeNull());
    expect(selected().id).toBe(`item-${ids[1]}`);
    expect(screen.getByText(`${items.length - 1} pending`)).toBeInTheDocument();
    expect(screen.getByText("1 confirmed")).toBeInTheDocument();

    await userEvent.keyboard("r");
    await waitFor(() => expect(decisions).toHaveLength(2));
    expect(decisions[1]).toMatchObject({ item_id: ids[1], decision: "reject" });

    // typing a note must not trigger shortcuts; n focuses the note of the current card
    await userEvent.keyboard("n");
    expect(document.activeElement).toBe(within(selected()).getByRole("textbox"));
    await userEvent.keyboard("cru looks fine");
    expect(decisions).toHaveLength(2);
    await userEvent.keyboard("{Escape}");
    expect(document.activeElement).toBe(document.body);
    await userEvent.keyboard("u");
    await waitFor(() => expect(decisions).toHaveLength(3));
    expect(decisions[2]).toEqual({ run_id: RUN, item_id: ids[2], decision: "unsure", note: "cru looks fine" });
    expect(screen.getByText("1 unsure")).toBeInTheDocument();
  });

  it("decision buttons work with the mouse and show the latest decision plus history count", async () => {
    setup();
    await screen.findByRole("heading", { name: RUN });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "all");
    const card = cards()[0];
    await userEvent.click(within(card).getByRole("button", { name: /Reject/ }));
    await waitFor(() => expect(within(card).getByRole("button", { name: /Reject/ })).toHaveAttribute("aria-pressed", "true"));
    expect(within(card).getByText("History (1)")).toBeInTheDocument();
    expect(within(card).getByText(/by tester/)).toBeInTheDocument();
    // change of mind appends a second record; the card shows the latest
    await userEvent.click(within(card).getByRole("button", { name: /Confirm/ }));
    await waitFor(() => expect(within(card).getByRole("button", { name: /Confirm/ })).toHaveAttribute("aria-pressed", "true"));
    expect(within(card).getByRole("button", { name: /Reject/ })).toHaveAttribute("aria-pressed", "false");
    expect(within(card).getByText("History (2)")).toBeInTheDocument();
  });

  it("loads and shows the full decision history, newest first", async () => {
    const decided = items.map((i, n) =>
      n === 0
        ? {
            ...i,
            status: "reject" as const,
            history_count: 2,
            decision: { ts: "2026-10-24T09:05:00Z", run_id: RUN, item_id: i.item_id, decision: "reject" as const, note: "second thoughts", reviewer: "tony" },
          }
        : i,
    );
    const hist = {
      run_id: RUN,
      history: [
        { ts: "2026-10-24T09:00:00Z", run_id: RUN, item_id: items[0].item_id, decision: "confirm", note: "first take", reviewer: "tony" },
        { ts: "2026-10-24T09:05:00Z", run_id: RUN, item_id: items[0].item_id, decision: "reject", note: "second thoughts", reviewer: "tony" },
      ],
    };
    setup({ items: decided, extra: { [`/review/history?run_id=${encodeURIComponent(RUN)}&item_id=${encodeURIComponent(items[0].item_id)}`]: hist } });
    await screen.findByRole("heading", { name: RUN });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "decided");
    const card = cards()[0];
    expect(within(card).getByText(/second thoughts/)).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "History (2)" }));
    const list = await within(card).findByRole("list", { name: /history/i });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("reject");
    expect(rows[0]).toHaveTextContent("(latest)");
    expect(rows[1]).toHaveTextContent("first take");
  });

  it("batch decide: disabled until a group is picked, asks for confirmation, then appends one decision per item", async () => {
    const { batches, decisions } = setup();
    await screen.findByRole("heading", { name: RUN });
    const batchBtn = screen.getByRole("button", { name: /Decide all/ });
    expect(batchBtn).toBeDisabled();
    const g = items.find((i) => i.kind === "behavior")!;
    const inGroup = items.filter((i) => i.group === g.group);
    await userEvent.selectOptions(screen.getByLabelText("Group"), g.group);
    expect(screen.getByRole("button", { name: /Decide all/ })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: /Decide all/ }));
    const dlg = screen.getByRole("dialog", { name: `Decide ${inGroup.length} item${inGroup.length === 1 ? "" : "s"} at once` });
    expect(batches).toHaveLength(0); // nothing sent before confirming
    await userEvent.click(within(dlg).getByLabelText("Reject"));
    await userEvent.type(within(dlg).getByRole("textbox"), "all false positives");
    await userEvent.click(within(dlg).getByRole("button", { name: /Record/ }));
    await waitFor(() => expect(batches).toHaveLength(1));
    expect(batches[0].run_id).toBe(RUN);
    expect(batches[0].decisions.map((d) => d.item_id).sort()).toEqual(inGroup.map((i) => i.item_id).sort());
    expect(batches[0].decisions.every((d) => d.decision === "reject" && d.note === "all false positives")).toBe(true);
    expect(decisions).toHaveLength(0);
    expect(await screen.findByText(`Recorded ${inGroup.length} “reject” decision${inGroup.length === 1 ? "" : "s"}.`)).toBeInTheDocument();
    expect(screen.getByText(`${inGroup.length} rejected`)).toBeInTheDocument();
  });

  it("batch can be cancelled without sending anything", async () => {
    const { batches } = setup();
    await screen.findByRole("heading", { name: RUN });
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "hazard");
    await userEvent.click(screen.getByRole("button", { name: /Decide all/ }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(batches).toHaveLength(0);
  });

  it("a failed decision shows the error and leaves the item pending", async () => {
    setup({ decide: () => ({ status: 500, body: { detail: "disk full" } }) });
    await screen.findByRole("heading", { name: RUN });
    await userEvent.keyboard("c");
    expect(await screen.findByText("disk full")).toBeInTheDocument();
    expect(cards()).toHaveLength(items.length);
    expect(screen.getByText(`${items.length} pending`)).toBeInTheDocument();
  });

  it("renders hostile evidence, notes, names and ids as text", async () => {
    const evil = "<img src=x onerror=\"window.__pwned=1\"><script>window.__pwned=1</script>";
    const hostile: ReviewItem[] = [
      {
        ...items[0],
        item_id: "h-evil",
        name: evil,
        group: evil,
        title: evil,
        evidence: evil,
        proposed_label: "confirm",
        draft_note: evil,
        status: "confirm",
        history_count: 1,
        decision: { ts: evil, run_id: RUN, item_id: "h-evil", decision: "confirm", note: evil, reviewer: evil },
      },
    ];
    setup({ items: hostile });
    await screen.findByRole("heading", { name: RUN });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "all");
    expect((await screen.findAllByText(evil, { exact: false })).length).toBeGreaterThan(2);
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });

  it("says when everything is decided", async () => {
    const done = items.map((i) => ({ ...i, status: "confirm" as const }));
    setup({ items: done });
    expect(await screen.findByText("All done")).toBeInTheDocument();
  });
});

describe("runs overview", () => {
  it("lists runs with their counters and links to each queue", async () => {
    mockFetch({ "/review/runs": runsFx });
    renderRoute(<ReviewView />, "/review", "/review");
    const link = await screen.findByRole("link", { name: RUN });
    expect(link).toHaveAttribute("href", `/review/${RUN}`);
    expect(screen.getByRole("progressbar", { name: "0 of 123 decided" })).toBeInTheDocument();
  });
});
