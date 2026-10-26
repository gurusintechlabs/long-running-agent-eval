// Spec editor API (docs/ui-api-specs.md section 1 and 3). All strings are untrusted: render as text only.
import { apiFetch } from "./client";

export type SpecData = Record<string, unknown>;

export interface SpecListEntry {
  name: string;
  source: "example" | "draft";
  editable: boolean;
  path: string;
  valid: boolean;
  spec_hash: string | null;
  errors: SpecIssue[];
  experiment_id: string | null;
  runtime: string | null;
  model: string | null;
  mtime: number | null;
}

export interface SpecListResponse {
  drafts_dir: string;
  examples_dir: string;
  specs: SpecListEntry[];
}

export interface SpecIssue {
  /** Dotted path of the form field (`task.honey.0.path`); "" = not tied to a field. */
  path: string;
  message: string;
  type?: string;
  group?: string;
  level?: "warning" | "info";
}

export interface SpecValidation {
  valid: boolean;
  errors: SpecIssue[];
  warnings: SpecIssue[];
  spec_hash: string | null;
  run_ids: string[];
  summary: Record<string, unknown>;
}

export interface SpecDetail extends SpecListEntry {
  data: SpecData;
  yaml: string;
  warnings: SpecIssue[];
  run_ids: string[];
  summary: Record<string, unknown>;
  validation: SpecValidation;
}

export interface FieldCondition {
  path: string;
  equals: unknown;
}

export interface FieldNote {
  level: "info" | "warning";
  when?: FieldCondition;
  text: string;
}

export interface SpecField {
  /** Dotted path into the spec data; `*` is a list index. */
  path: string;
  key: string;
  label?: string;
  help?: string;
  section?: string;
  kind: string;
  widget?: string;
  required?: boolean;
  nullable?: boolean;
  default?: unknown;
  min?: number;
  max?: number;
  exclusive_min?: number;
  exclusive_max?: number;
  min_items?: number;
  options?: unknown[];
  multiple?: boolean;
  unit?: string;
  advanced?: boolean;
  fields?: SpecField[];
  item_kind?: string;
  path_kind?: "file" | "dir" | "file_or_dir";
  relative_to?: string;
  pattern?: string;
  suggestions?: string[];
  placeholder?: string;
  item_hint?: string;
  visible_if?: FieldCondition;
  required_if?: FieldCondition;
  notes?: FieldNote[];
  fallback?: boolean;
}

export interface SpecSection {
  id: string;
  label: string;
  help?: string;
}

export interface CrossFieldNote {
  level: "info" | "warning";
  paths: string[];
  when?: FieldCondition;
  text: string;
}

export interface SpecSchema {
  version: number;
  widgets: string[];
  sections: SpecSection[];
  fields: SpecField[];
  cross_field_notes: CrossFieldNote[];
  json_schema?: unknown;
}

export interface SpecPathSuggestion {
  value: string;
  repo_path: string;
  kind: "file" | "dir";
}

export interface SaveResponse extends SpecValidation {
  saved: boolean;
  name: string;
  source: "draft";
  path: string;
}

/** Exactly one of data / yaml. */
export type SpecInput = { data: SpecData } | { yaml: string };

const enc = encodeURIComponent;

export const specsApi = {
  list: (signal?: AbortSignal) => apiFetch<SpecListResponse>("/specs", { signal }),
  schema: (signal?: AbortSignal) => apiFetch<SpecSchema>("/specs/schema", { signal }),
  get: (name: string, source?: "draft" | "example", signal?: AbortSignal) =>
    apiFetch<SpecDetail>(`/specs/${enc(name)}${source ? `?source=${source}` : ""}`, { signal }),
  validate: (input: SpecInput, signal?: AbortSignal) =>
    apiFetch<SpecValidation>("/specs/validate", { method: "POST", body: input, signal }),
  save: (name: string, input: SpecInput, overwrite: boolean) =>
    apiFetch<SaveResponse>("/specs/save", { method: "POST", body: { name, ...input, overwrite } }),
  duplicate: (name: string, newName: string, source: "draft" | "example", overwrite = false) =>
    apiFetch<SaveResponse>(`/specs/${enc(name)}/duplicate`, {
      method: "POST",
      body: { new_name: newName, source, overwrite },
    }),
  remove: (name: string) => apiFetch<{ deleted: boolean }>(`/specs/${enc(name)}`, { method: "DELETE" }),
  paths: (q: string, signal?: AbortSignal) =>
    apiFetch<{ paths: SpecPathSuggestion[] }>(`/specs/paths?q=${enc(q)}`, { signal }),
};
