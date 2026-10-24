// Pure helpers for the schema-driven spec form. No React here, so they are easy to test.
import type { FieldCondition, SpecData, SpecField, SpecIssue, SpecSchema, SpecSection } from "../../api";

export type Seg = string | number;
export type Json = unknown;

export const KNOWN_WIDGETS = [
  "text",
  "textarea",
  "number",
  "select",
  "checkbox",
  "path",
  "string_list",
  "object",
  "object_list",
  "json",
] as const;
export type Widget = (typeof KNOWN_WIDGETS)[number];

export function splitPath(p: string): Seg[] {
  if (!p) return [];
  return p.split(".").map((s) => (/^\d+$/.test(s) ? Number(s) : s));
}

export function joinPath(base: string, ...segs: Seg[]): string {
  return [base, ...segs.map(String)].filter((s) => s !== "").join(".");
}

/** `task.honey.0.path` -> `task.honey.*.path` */
export function schemaPathOf(concrete: string): string {
  return concrete
    .split(".")
    .map((s) => (/^\d+$/.test(s) ? "*" : s))
    .join(".");
}

export function isObj(v: Json): v is Record<string, Json> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function getAt(data: Json, segs: readonly Seg[]): Json {
  let cur: Json = data;
  for (const s of segs) {
    if (Array.isArray(cur) && typeof s === "number") cur = cur[s];
    else if (isObj(cur)) cur = cur[String(s)];
    else return undefined;
  }
  return cur;
}

/**
 * Immutable set. `undefined` deletes the key (or, for an array index, the item) and prunes object
 * ancestors that became empty, so an untouched optional group never lingers as `{}`.
 */
export function setAt(data: SpecData, segs: readonly Seg[], value: Json): SpecData {
  if (segs.length === 0) return (isObj(value) ? value : {}) as SpecData;
  const [head, ...rest] = segs;
  const cur: Json = typeof head === "number" ? undefined : data[head];
  const next = rest.length === 0 ? value : setIn(cur, rest, value);
  const out: SpecData = { ...data };
  if (next === undefined) delete out[String(head)];
  else out[String(head)] = next;
  return out;
}

function setIn(cur: Json, segs: readonly Seg[], value: Json): Json {
  const [head, ...rest] = segs;
  if (typeof head === "number") {
    const arr = Array.isArray(cur) ? [...cur] : [];
    const nextItem = rest.length === 0 ? value : setIn(arr[head], rest, value);
    if (nextItem === undefined) arr.splice(head, 1);
    else arr[head] = nextItem;
    return arr;
  }
  const obj: Record<string, Json> = isObj(cur) ? { ...cur } : {};
  const nextVal = rest.length === 0 ? value : setIn(obj[head], rest, value);
  if (nextVal === undefined) delete obj[head];
  else obj[head] = nextVal;
  // prune empty containers created by edits (but never an empty array: lists may be intentionally empty)
  return nextVal === undefined && Object.keys(obj).length === 0 ? undefined : obj;
}

export function evalCond(cond: FieldCondition | undefined, data: SpecData, indices: Seg[] = []): boolean {
  if (!cond) return true;
  let path = cond.path;
  if (path.includes("*")) {
    // a condition inside a list row refers to the same row: fill `*` from the row indices
    const idx = [...indices].filter((s) => typeof s === "number");
    let n = 0;
    path = path
      .split(".")
      .map((s) => (s === "*" ? String(idx[n++] ?? 0) : s))
      .join(".");
  }
  return getAt(data, splitPath(path)) === cond.equals;
}

/** Drop null, "" and undefined the way the server does for optional fields. */
export function normalize(v: Json): Json {
  if (Array.isArray(v)) return v.map(normalize);
  if (isObj(v)) {
    const out: Record<string, Json> = {};
    for (const k of Object.keys(v).sort()) {
      const x = v[k];
      if (x === null || x === undefined || x === "") continue;
      out[k] = normalize(x);
    }
    return out;
  }
  return v;
}

export function sameData(a: SpecData, b: SpecData): boolean {
  return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b));
}

/** Widget to render: the declared one if we know it, else a generic one chosen from the field kind. */
export function resolveWidget(f: SpecField): Widget {
  if (f.widget && (KNOWN_WIDGETS as readonly string[]).includes(f.widget)) {
    // a declared widget that cannot work for the field's shape falls back to JSON
    if (f.widget === "object" && !f.fields) return "json";
    if (f.widget === "object_list" && !f.fields) return "json";
    if (f.widget === "select" && !f.options) return f.kind === "boolean" ? "checkbox" : "json";
    return f.widget as Widget;
  }
  switch (f.kind) {
    case "boolean":
      return "checkbox";
    case "integer":
    case "number":
      return "number";
    case "string":
      return "text";
    case "enum":
      return f.options ? "select" : "text";
    case "object":
      return f.fields ? "object" : "json";
    case "list":
      return f.item_kind === "string" ? "string_list" : f.item_kind === "object" && f.fields ? "object_list" : "json";
    default:
      return "json";
  }
}

export function isGeneric(f: SpecField): boolean {
  return !!f.fallback || !f.widget || !(KNOWN_WIDGETS as readonly string[]).includes(f.widget);
}

export interface SectionBlock {
  section: SpecSection;
  roots: SpecField[];
  /** every field in the block is advanced: the whole block starts collapsed */
  allAdvanced: boolean;
}

function walkRoots(fields: SpecField[], id: string, parentSection: string | undefined, out: SpecField[]) {
  for (const f of fields) {
    if (f.section === id && parentSection !== id) out.push(f);
    if (f.kind === "object" && f.fields) walkRoots(f.fields, id, f.section, out);
  }
}

/** Group the field tree by section (nested objects with their own section become their own block). */
export function sectionBlocks(schema: SpecSchema): SectionBlock[] {
  const blocks: SectionBlock[] = [];
  const known = new Set<string>();
  for (const section of schema.sections) {
    known.add(section.id);
    const roots: SpecField[] = [];
    walkRoots(schema.fields, section.id, undefined, roots);
    if (roots.length) blocks.push({ section, roots, allAdvanced: roots.every((r) => !!r.advanced) });
  }
  // a field whose section is not declared still gets shown: never drop a field
  const orphans: SpecField[] = [];
  for (const f of schema.fields) if (!f.section || !known.has(f.section)) orphans.push(f);
  if (orphans.length) blocks.push({ section: { id: "other", label: "Other" }, roots: orphans, allAdvanced: false });
  return blocks;
}

/** Children of an object field that belong in it (those with their own section are separate blocks). */
export function ownChildren(f: SpecField): SpecField[] {
  return (f.fields ?? []).filter((c) => !c.section || !f.section || c.section === f.section);
}

export function fieldId(path: string): string {
  return `f:${path}`;
}

export function inputId(path: string): string {
  return `i:${path}`;
}

export interface IssueIndex {
  byPath: Map<string, SpecIssue[]>;
  all: SpecIssue[];
}

export function indexIssues(issues: SpecIssue[]): IssueIndex {
  const byPath = new Map<string, SpecIssue[]>();
  for (const i of issues) {
    const list = byPath.get(i.path) ?? [];
    list.push(i);
    byPath.set(i.path, list);
  }
  return { byPath, all: issues };
}

export function issuesUnder(idx: IssueIndex, path: string): number {
  let n = 0;
  const prefix = `${path}.`;
  for (const [p, list] of idx.byPath) if (p === path || p.startsWith(prefix)) n += list.length;
  return n;
}

/** Walk the field tree and return every concrete path of keys present in `data` but unknown to the schema. */
export function findExtraKeys(fields: SpecField[], data: Json, base = ""): string[] {
  if (!isObj(data)) return [];
  const known = new Map(fields.map((f) => [f.key, f]));
  const out: string[] = [];
  for (const k of Object.keys(data)) {
    const f = known.get(k);
    const p = joinPath(base, k);
    if (!f) {
      out.push(p);
      continue;
    }
    if (f.kind === "object" && f.fields) out.push(...findExtraKeys(f.fields, data[k], p));
    else if (f.kind === "list" && f.fields && Array.isArray(data[k])) {
      (data[k] as Json[]).forEach((row, i) => out.push(...findExtraKeys(f.fields!, row, joinPath(p, i))));
    }
  }
  return out;
}

/** The schema field (path with `*`) for a concrete path, or null. */
export function findField(fields: SpecField[], concrete: string): SpecField | null {
  const want = schemaPathOf(concrete);
  const walk = (fs: SpecField[]): SpecField | null => {
    for (const f of fs) {
      if (f.path === want) return f;
      if (f.fields && (want === f.path || want.startsWith(`${f.path}.`))) {
        const r = walk(f.fields);
        if (r) return r;
      }
    }
    return null;
  };
  return walk(fields);
}

/** Keys of the disclosure panels that must be open to show `concrete` (all ancestors, section included). */
export function revealKeys(schema: SpecSchema, concrete: string): string[] {
  const segs = concrete.split(".");
  const keys: string[] = [];
  for (let i = 1; i <= segs.length; i++) keys.push(`adv:${segs.slice(0, i).join(".")}`);
  let sec = findField(schema.fields, concrete)?.section;
  for (let i = segs.length - 1; i >= 1 && !sec; i--) sec = findField(schema.fields, segs.slice(0, i).join("."))?.section;
  if (!sec) sec = findField(schema.fields, segs[0])?.section;
  if (sec) keys.push(`sec:${sec}`);
  return keys;
}

export function emptyRow(): SpecData {
  return {};
}

export function moveItem<T>(arr: T[], from: number, to: number): T[] {
  if (to < 0 || to >= arr.length || from === to) return arr;
  const out = [...arr];
  const [x] = out.splice(from, 1);
  out.splice(to, 0, x);
  return out;
}
