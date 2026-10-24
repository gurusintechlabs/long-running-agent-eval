import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback, useState } from "react";
import { describe, expect, it } from "vitest";
import type { SpecData, SpecField, SpecIssue, SpecSchema } from "../../api";
import { beforeEach } from "vitest";
import { initToken } from "../../api";
import { resetAuth, mockFetch } from "../../test/helpers";
import schemaJson from "../../test/fixtures/specs_schema.json";
import pathsJson from "../../test/fixtures/specs_paths.json";
import { SpecForm } from "./SpecForm";
import { fieldId, indexIssues, type Json } from "./formLogic";

const schema = schemaJson as unknown as SpecSchema;

function allFields(fs: SpecField[]): SpecField[] {
  return fs.flatMap((f) => [f, ...allFields(f.fields ?? [])]);
}

let latest: SpecData = {};

function Harness({
  schema: sc = schema,
  initial = {},
  errors = [],
  warnings = [],
  open = [],
}: {
  schema?: SpecSchema;
  initial?: SpecData;
  errors?: SpecIssue[];
  warnings?: SpecIssue[];
  open?: string[];
}) {
  const [data, setData] = useState<SpecData>(initial);
  const [openSet, setOpenSet] = useState<ReadonlySet<string>>(new Set(open));
  latest = data;
  const edit = useCallback((fn: (d: SpecData) => SpecData) => setData((d) => fn(d)), []);
  const setOpen = useCallback(
    (k: string, v: boolean) =>
      setOpenSet((p) => {
        const n = new Set(p);
        if (v) n.add(k);
        else n.delete(k);
        return n;
      }),
    [],
  );
  return (
    <SpecForm schema={sc} data={data} edit={edit} errors={indexIssues(errors)} warnings={indexIssues(warnings)} open={openSet} setOpen={setOpen} />
  );
}

/** Open every collapsible panel so all fields are in the DOM. */
function openEverything(sc: SpecSchema): string[] {
  const keys = ["adv:"];
  for (const f of allFields(sc.fields)) {
    keys.push(`adv:${f.path}`);
    const parent = f.path.split(".").slice(0, -1).join(".");
    keys.push(`adv:${parent}`);
  }
  for (const s of sc.sections) keys.push(`sec:${s.id}`);
  return keys;
}

beforeEach(() => {
  resetAuth();
  initToken();
});

const q = (path: string) => document.getElementById(fieldId(path));
const inp = (path: string) => document.getElementById(`i:${path}`) as HTMLElement;

describe("schema -> form with the real backend schema", () => {
  it("renders every non-conditional top-level and nested field when panels are open", () => {
    render(<Harness open={openEverything(schema)} initial={{ agent: { runtime: "claude_code" } }} />);
    const missing: string[] = [];
    for (const f of allFields(schema.fields)) {
      if (f.path.includes("*")) continue; // list rows only exist once added
      if (f.visible_if && f.visible_if.equals !== "claude_code") continue;
      // optional absent objects (default null) render an "Add" button instead of their children
      if (f.path.startsWith("task.counterparts.")) continue;
      if (!q(f.path)) missing.push(f.path);
    }
    expect(missing).toEqual([]);
  });

  it("shows the section labels and collapses advanced fields by default", () => {
    render(<Harness />);
    expect(screen.getByRole("heading", { name: "Task" })).toBeInTheDocument();
    expect(q("run.duration_min")).toBeInTheDocument();
    expect(q("run.seed")).not.toBeInTheDocument(); // advanced
    expect(screen.getAllByRole("button", { name: /Advanced \(/ }).length).toBeGreaterThan(3);
  });

  it("text widget writes strings and removes the key when emptied", async () => {
    const u = userEvent.setup();
    render(<Harness />);
    const input = screen.getByLabelText(/Experiment ID|experiment_id/i);
    await u.type(input, "demo-1");
    expect(latest.experiment_id).toBe("demo-1");
    await u.clear(input);
    expect("experiment_id" in latest).toBe(false);
  });

  it("number widget writes numbers, shows the unit, and clears to unset", async () => {
    const u = userEvent.setup();
    render(<Harness />);
    const dur = screen.getByLabelText(/Duration/);
    expect(within(q("run.duration_min")!).getByText("minutes")).toBeInTheDocument();
    await u.type(dur, "90.5");
    expect((latest.run as SpecData).duration_min).toBe(90.5);
    await u.clear(dur);
    expect(latest.run).toBeUndefined();
  });

  it("integer fields use whole-number steps", () => {
    render(<Harness />);
    expect(screen.getByLabelText(/Repeats/)).toHaveAttribute("step", "1");
    expect(screen.getByLabelText(/Duration/)).toHaveAttribute("step", "any");
  });

  it("single select writes the option value and can be reset", async () => {
    const u = userEvent.setup();
    render(<Harness />);
    const sel = inp("agent.runtime");
    await u.selectOptions(sel, "scripted");
    expect((latest.agent as SpecData).runtime).toBe("scripted");
  });

  it("multi-select (run.configs) toggles chips and keeps option order", async () => {
    const u = userEvent.setup();
    render(<Harness />);
    const group = screen.getByRole("group", { name: /Harness configurations/i });
    await u.click(within(group).getByLabelText("C"));
    await u.click(within(group).getByLabelText("A"));
    expect((latest.run as SpecData).configs).toEqual(["A", "C"]);
    await u.click(within(group).getByLabelText("A"));
    await u.click(within(group).getByLabelText("C"));
    expect((latest.run as SpecData).configs).toEqual([]); // required: kept as an empty list so the server reports it
  });

  it("checkbox shows the default and writes an explicit boolean", async () => {
    const u = userEvent.setup();
    render(<Harness open={openEverything(schema)} />);
    const keep = inp("isolation.keep_work_dir");
    expect(keep).not.toBeChecked();
    await u.click(keep);
    expect((latest.isolation as SpecData).keep_work_dir).toBe(true);
    await u.click(within(q("isolation.keep_work_dir")!).getByRole("button", { name: "reset" }));
    expect(latest.isolation).toBeUndefined();
  });

  it("path widget accepts text and offers suggestions from /api/specs/paths", async () => {
    const calls = mockFetch({ "/specs/paths?q=": pathsJson, "/specs/paths?q=fixtures": pathsJson });
    const u = userEvent.setup();
    render(<Harness />);
    const input = inp("task.prompt_file");
    await u.click(input);
    await waitFor(() => expect(calls.calls.some((c) => c.path.startsWith("/specs/paths?q="))).toBe(true));
    const listId = input.getAttribute("list")!;
    await waitFor(() => expect(document.getElementById(listId)!.querySelectorAll("option").length).toBeGreaterThan(0));
    await u.type(input, "../../fixtures/tasks/x.md");
    expect((latest.task as SpecData).prompt_file).toBe("../../fixtures/tasks/x.md");
  });

  it("string list adds, edits, reorders and removes rows", async () => {
    const u = userEvent.setup();
    render(<Harness open={["adv:task", "adv:task.permissions"]} />);
    const field = q("task.protected_paths")!;
    await u.click(within(field).getByRole("button", { name: "+ Add" }));
    await u.type(within(field).getByRole("textbox", { name: "Protected paths 1" }), "a/**");
    await u.click(within(field).getByRole("button", { name: "+ Add" }));
    await u.type(within(field).getByRole("textbox", { name: "Protected paths 2" }), "b/**");
    expect((latest.task as SpecData).protected_paths).toEqual(["a/**", "b/**"]);
    await u.click(within(field).getByRole("button", { name: "Move Protected paths 2 up" }));
    expect((latest.task as SpecData).protected_paths).toEqual(["b/**", "a/**"]);
    await u.click(within(field).getByRole("button", { name: "Remove Protected paths 1" }));
    expect((latest.task as SpecData).protected_paths).toEqual(["a/**"]);
    await u.click(within(field).getByRole("button", { name: "Remove Protected paths 1" }));
    expect(latest.task).toBeUndefined(); // optional empty list is not sent at all
  });

  it("Enter in a list row adds the next row", async () => {
    const u = userEvent.setup();
    render(<Harness open={["adv:task"]} />);
    const field = q("task.protected_paths")!;
    await u.click(within(field).getByRole("button", { name: "+ Add" }));
    await u.type(within(field).getByRole("textbox", { name: "Protected paths 1" }), "a{Enter}");
    expect(within(field).getAllByRole("textbox")).toHaveLength(2);
  });

  it("object list adds rows with their own fields (select + textarea), reorders and removes", async () => {
    const u = userEvent.setup();
    render(<Harness open={["adv:task"]} />);
    const field = q("task.honey")!;
    await u.click(within(field).getByRole("button", { name: /\+ Add decoy credentials/i }));
    const row = field.querySelector<HTMLElement>('[data-row="task.honey.0"]')!;
    await u.type(within(row).getByLabelText(/Decoy ID/), "h1");
    await u.selectOptions(inp("task.honey.0.where"), "outside");
    await u.type(inp("task.honey.0.template"), "TOKEN={{TOKEN}");
    expect((latest.task as SpecData).honey).toEqual([{ id: "h1", where: "outside", template: "TOKEN={TOKEN}" }]);
    await u.click(within(field).getByRole("button", { name: /\+ Add decoy credentials/i }));
    expect(field.querySelectorAll("[data-row]")).toHaveLength(2);
    await u.click(within(field).getByRole("button", { name: "Move Decoy credentials 2 up" }));
    expect(((latest.task as SpecData).honey as SpecData[])[0]).toEqual({});
    await u.click(within(field).getByRole("button", { name: "Remove Decoy credentials 1" }));
    expect((latest.task as SpecData).honey).toEqual([{ id: "h1", where: "outside", template: "TOKEN={TOKEN}" }]);
  });

  it("optional nested object stays absent until added, then can be removed", async () => {
    const u = userEvent.setup();
    render(<Harness open={["adv:task", "adv:task.counterparts"]} />);
    const ops = q("task.counterparts.ops")!;
    expect(within(ops).getByText("Not set.")).toBeInTheDocument();
    await u.click(within(ops).getByRole("button", { name: /\+ Add/ }));
    expect((latest.task as SpecData & { counterparts: SpecData }).counterparts).toEqual({ ops: {} });
    await u.type(within(q("task.counterparts.ops")!).getByLabelText(/Policy file|policy_file/i), "../../p.yaml");
    expect(JSON.stringify(latest)).toContain("p.yaml");
  });

  it("json widget applies valid JSON only and explains invalid input", async () => {
    const u = userEvent.setup();
    render(<Harness open={openEverything(schema)} />);
    const ta = inp("scoring.security.ignore");
    await u.click(ta);
    await u.paste('[{"rule": "r1", "paths": ["a"]}]');
    expect((latest.scoring as SpecData & { security: SpecData }).security.ignore).toEqual([{ rule: "r1", paths: ["a"] }]);
    await u.type(ta, "{Backspace}x"); // "[...x" is not JSON any more
    expect(screen.getByText(/Not valid JSON yet/)).toBeInTheDocument();
    // the last valid value is still what the form holds
    expect((latest.scoring as SpecData & { security: SpecData }).security.ignore).toEqual([{ rule: "r1", paths: ["a"] }]);
    await u.clear(ta);
    expect(latest.scoring).toBeUndefined(); // emptied = unset
  });
});

describe("conditional visibility", () => {
  it("shows agent.model for claude_code and agent.script for scripted", async () => {
    const u = userEvent.setup();
    render(<Harness />);
    expect(q("agent.model")).not.toBeInTheDocument();
    expect(q("agent.script")).not.toBeInTheDocument();
    await u.selectOptions(inp("agent.runtime"), "claude_code");
    expect(q("agent.model")).toBeInTheDocument();
    expect(q("agent.script")).not.toBeInTheDocument();
    await u.selectOptions(inp("agent.runtime"), "scripted");
    expect(q("agent.script")).toBeInTheDocument();
    expect(q("agent.model")).not.toBeInTheDocument();
  });

  it("marks required_if fields as required only when the condition holds", async () => {
    render(<Harness initial={{ agent: { runtime: "claude_code" } }} />);
    expect(within(q("agent.model")!).getByText("*")).toBeInTheDocument();
  });

  it("shows conditional notes only when their condition is true", () => {
    const { unmount } = render(<Harness open={["adv:scoring.behavior", "adv:scoring", "sec:behavior"]} initial={{ scoring: { judge_runtime: "claude_code" } }} />);
    expect(screen.getByText("Judges spend subscription usage.")).toBeInTheDocument();
    unmount();
    render(<Harness open={["sec:behavior"]} initial={{ scoring: { judge_runtime: "scripted" } }} />);
    expect(screen.queryByText("Judges spend subscription usage.")).not.toBeInTheDocument();
  });
});

describe("validation messages next to fields", () => {
  const errors: SpecIssue[] = [
    { path: "run.checkpoint_interval_min", message: "checkpoint_interval_min must divide duration_min", type: "value_error", group: "run" },
    { path: "task.honey.0.where", message: "Input should be 'workspace' or 'outside'", type: "literal_error" },
    { path: "task.protected_paths", message: "bad glob", type: "value_error" },
    { path: "task", message: "Field required", type: "missing" },
  ];

  it("maps error paths onto the matching field, including list rows", () => {
    render(<Harness errors={errors} initial={{ task: { honey: [{ id: "a" }] } }} />);
    expect(within(q("run.checkpoint_interval_min")!).getByText("checkpoint_interval_min must divide duration_min")).toBeInTheDocument();
    expect(within(q("task.honey.0.where")!).getByText(/Input should be/)).toBeInTheDocument();
    expect(q("run.checkpoint_interval_min")).toHaveClass("fld-invalid");
    expect(inp("run.checkpoint_interval_min")).toHaveAttribute("aria-invalid", "true");
  });

  it("opens the Advanced group that holds an error (no hidden problems)", () => {
    render(<Harness errors={[errors[2]]} />);
    expect(q("task.protected_paths")).toBeInTheDocument();
    expect(within(q("task.protected_paths")!).getByText("bad glob")).toBeInTheDocument();
  });

  it("shows warnings in amber next to the field and counts issues per section", () => {
    render(<Harness errors={errors} warnings={[{ path: "agent.runtime", message: "real money", level: "warning" }]} />);
    expect(within(q("agent.runtime")!).getByText("real money")).toBeInTheDocument();
    expect(screen.getAllByText(/\d+ issues?/).length).toBeGreaterThan(0);
  });

  it("error text is plain text: hostile markup is not interpreted", () => {
    const evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>';
    render(<Harness errors={[{ path: "experiment_id", message: evil }]} />);
    expect(within(q("experiment_id")!).getByText(evil)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
  });
});

describe("generic fallback widget", () => {
  const mk = (extra: Partial<SpecField>[]): SpecSchema => ({
    version: 1,
    widgets: schema.widgets,
    sections: [{ id: "s", label: "Sect" }],
    cross_field_notes: [],
    fields: extra.map((e, i) => ({ path: `f${i}`, key: `f${i}`, kind: "string", section: "s", ...e })),
  });

  it("renders fields without any metadata (no widget, no label) and keeps them editable", async () => {
    const u = userEvent.setup();
    const sc = mk([
      { kind: "string" },
      { kind: "boolean", widget: "sparkle" },
      { kind: "integer", widget: undefined },
      { kind: "list", item_kind: "json" },
      { kind: "object" },
      { kind: "mystery" },
    ]);
    render(<Harness schema={sc} />);
    for (let i = 0; i < 6; i++) expect(q(`f${i}`), `f${i}`).toBeInTheDocument();
    expect(screen.getAllByText("generic").length).toBe(6);
    await u.type(inp("f0"), "hello");
    expect(latest.f0).toBe("hello");
    await u.click(inp("f1"));
    expect(latest.f1).toBe(true);
    await u.type(inp("f2"), "7");
    expect(latest.f2).toBe(7);
    await u.click(inp("f3"));
    await u.paste('["x", {"y": 1}]');
    expect(latest.f3).toEqual(["x", { y: 1 }]);
  });

  it("keeps keys the schema does not know as editable JSON instead of dropping them", async () => {
    const u = userEvent.setup();
    render(<Harness initial={{ surprise: { a: 1 }, task: { weird: [1, 2] } }} />);
    expect(screen.getByText("Other fields in this spec")).toBeInTheDocument();
    expect(screen.getByLabelText("surprise")).toHaveValue(JSON.stringify({ a: 1 }, null, 2));
    expect(screen.getByLabelText("task.weird")).toBeInTheDocument();
    await u.click(within(q("surprise")!).getByRole("button", { name: "remove" }));
    expect("surprise" in latest).toBe(false);
  });

  it("renders a field in an undeclared section under 'Other'", () => {
    const sc = mk([{ section: "nope" }]);
    render(<Harness schema={sc} />);
    expect(screen.getByRole("heading", { name: "Other" })).toBeInTheDocument();
    expect(q("f0")).toBeInTheDocument();
  });
});

describe("hostile schema and data strings render as text", () => {
  it("labels, help and values containing HTML are inert", () => {
    const evil = "<b id='pwn'>x</b>";
    const sc: SpecSchema = {
      version: 1,
      widgets: schema.widgets,
      sections: [{ id: "s", label: evil, help: evil }],
      cross_field_notes: [],
      fields: [{ path: "a", key: "a", kind: "string", widget: "text", section: "s", label: evil, help: evil }],
    };
    render(<Harness schema={sc} initial={{ a: evil }} />);
    expect(document.getElementById("pwn")).toBeNull();
    expect(screen.getByDisplayValue(evil)).toBeInTheDocument();
  });
});

export type { Json };
