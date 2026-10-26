import { describe, expect, it } from "vitest";
import type { SpecField, SpecSchema } from "../../api";
import schemaJson from "../../test/fixtures/specs_schema.json";
import {
  evalCond,
  findExtraKeys,
  findField,
  getAt,
  isGeneric,
  moveItem,
  normalize,
  resolveWidget,
  revealKeys,
  sameData,
  schemaPathOf,
  sectionBlocks,
  setAt,
  splitPath,
} from "./formLogic";

const schema = schemaJson as unknown as SpecSchema;

function allFields(fs: SpecField[]): SpecField[] {
  return fs.flatMap((f) => [f, ...allFields(f.fields ?? [])]);
}

describe("paths and updates", () => {
  it("splits dotted paths with numeric indices", () => {
    expect(splitPath("task.honey.0.path")).toEqual(["task", "honey", 0, "path"]);
    expect(schemaPathOf("task.honey.12.path")).toBe("task.honey.*.path");
  });

  it("sets immutably and creates intermediate containers", () => {
    const a = { run: { repeats: 1 } };
    const b = setAt(a, splitPath("run.duration_min"), 60);
    expect(b).toEqual({ run: { repeats: 1, duration_min: 60 } });
    expect(a).toEqual({ run: { repeats: 1 } });
    expect(setAt({}, splitPath("task.honey.1.id"), "x")).toEqual({ task: { honey: [undefined, { id: "x" }] } });
  });

  it("deleting the last key prunes empty parents but keeps explicit empty arrays", () => {
    expect(setAt({ a: { b: { c: 1 } }, k: 1 }, splitPath("a.b.c"), undefined)).toEqual({ k: 1 });
    expect(setAt({ a: { l: ["x"] } }, splitPath("a.l"), [])).toEqual({ a: { l: [] } });
  });

  it("deleting a list index removes the row", () => {
    expect(setAt({ l: [{ a: 1 }, { a: 2 }] }, splitPath("l.0"), undefined)).toEqual({ l: [{ a: 2 }] });
    expect(getAt({ l: [{ a: 1 }, { a: 2 }] }, splitPath("l.1.a"))).toBe(2);
  });

  it("moves items", () => {
    expect(moveItem([1, 2, 3], 0, 1)).toEqual([2, 1, 3]);
    expect(moveItem([1, 2, 3], 0, -1)).toEqual([1, 2, 3]);
  });
});

describe("conditions and comparison", () => {
  it("evaluates equals conditions on the form data", () => {
    const c = { path: "agent.runtime", equals: "scripted" };
    expect(evalCond(c, { agent: { runtime: "scripted" } })).toBe(true);
    expect(evalCond(c, { agent: { runtime: "claude_code" } })).toBe(false);
    expect(evalCond(c, {})).toBe(false);
    expect(evalCond(undefined, {})).toBe(true);
  });

  it("normalizes like the server (drops null and empty strings) so untouched forms are not dirty", () => {
    expect(sameData({ a: 1, b: null, c: "" }, { a: 1 })).toBe(true);
    expect(sameData({ a: 1, b: { x: "" } }, { a: 1, b: {} })).toBe(true);
    expect(sameData({ a: 1 }, { a: 2 })).toBe(false);
    expect(normalize({ b: 1, a: [null, { z: "" }] })).toEqual({ a: [null, {}], b: 1 });
  });
});

describe("schema handling with the real backend schema", () => {
  it("every declared widget is one the form knows", () => {
    for (const f of allFields(schema.fields)) {
      expect(schema.widgets).toContain(f.widget);
    }
  });

  it("covers every widget type at least once (so each is tested below)", () => {
    const used = new Set(allFields(schema.fields).map((f) => resolveWidget(f)));
    for (const w of schema.widgets) expect(used.has(w as never)).toBe(true);
  });

  it("puts every schema field into some section block: nothing is dropped", () => {
    const blocks = sectionBlocks(schema);
    const reachable = new Set<string>();
    const visit = (fs: SpecField[]) => {
      for (const f of fs) {
        reachable.add(f.path);
        visit(f.fields ?? []);
      }
    };
    visit(blocks.flatMap((b) => b.roots));
    for (const f of allFields(schema.fields)) expect(reachable.has(f.path), f.path).toBe(true);
  });

  it("finds fields by concrete path and builds reveal keys for nested advanced groups", () => {
    expect(findField(schema.fields, "task.honey.3.where")?.widget).toBe("select");
    const keys = revealKeys(schema, "task.counterparts.ops.policy_file");
    expect(keys).toContain("adv:task.counterparts");
    expect(keys).toContain("sec:task");
  });

  it("falls back to a generic widget by kind when the metadata is missing or unknown", () => {
    const mk = (o: Partial<SpecField>): SpecField => ({ path: "x", key: "x", kind: "string", ...o });
    expect(resolveWidget(mk({ kind: "boolean" }))).toBe("checkbox");
    expect(resolveWidget(mk({ kind: "integer", widget: "slider" }))).toBe("number");
    expect(resolveWidget(mk({ kind: "enum", options: ["a"] }))).toBe("select");
    expect(resolveWidget(mk({ kind: "list", item_kind: "string" }))).toBe("string_list");
    expect(resolveWidget(mk({ kind: "list", item_kind: "json" }))).toBe("json");
    expect(resolveWidget(mk({ kind: "object" }))).toBe("json");
    expect(resolveWidget(mk({ kind: "mystery" }))).toBe("json");
    expect(isGeneric(mk({ widget: "slider" }))).toBe(true);
    expect(isGeneric(mk({ widget: "text" }))).toBe(false);
  });

  it("reports data keys the schema does not know", () => {
    const extra = findExtraKeys(schema.fields, {
      experiment_id: "x",
      surprise: 1,
      task: { id: "t", mystery: true, honey: [{ id: "a", bogus: 1 }] },
    });
    expect(extra.sort()).toEqual(["surprise", "task.honey.0.bogus", "task.mystery"]);
  });
});
