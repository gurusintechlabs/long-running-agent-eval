// YAML conversion for the secondary YAML tab. The `yaml` package is loaded on demand (own chunk), and its default
// "core" schema is used: no custom tags, no code. The server stays the authority on validity.
import type { SpecData } from "../../api";

export async function toYaml(data: SpecData): Promise<string> {
  const { stringify } = await import("yaml");
  return stringify(data, { indent: 2, lineWidth: 100 });
}

export type ParseResult = { ok: true; data: SpecData } | { ok: false; error: string };

export async function parseYaml(text: string): Promise<ParseResult> {
  const { parse } = await import("yaml");
  try {
    const v: unknown = parse(text);
    if (v === null || v === undefined) return { ok: true, data: {} };
    if (typeof v !== "object" || Array.isArray(v)) return { ok: false, error: "The top level of a spec must be a mapping (key: value)." };
    return { ok: true, data: v as SpecData };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "cannot parse YAML" };
  }
}
