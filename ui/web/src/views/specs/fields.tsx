// Widgets of the schema-driven spec form. Every string from the schema, the data or the server is rendered as
// React text (UI-5); nothing here builds HTML.
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { specsApi, type SpecField, type SpecIssue, type SpecPathSuggestion } from "../../api";
import { useForm } from "./formContext";
import {
  evalCond,
  fieldId,
  getAt,
  inputId,
  isGeneric,
  isObj,
  issuesUnder,
  joinPath,
  moveItem,
  ownChildren,
  resolveWidget,
  schemaPathOf,
  splitPath,
  type Json,
  type Seg,
} from "./formLogic";

interface FieldProps {
  field: SpecField;
  /** Concrete dotted path (list indices filled in). */
  path: string;
  indices: Seg[];
  /** Section-level object: render its children without a box. */
  bare?: boolean;
  /** Inside an Advanced group already: do not nest another one. */
  inAdvanced?: boolean;
}

function label(f: SpecField): string {
  return f.label || f.key;
}

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

// ---------- shared chrome ----------

function Issues({ path, kind }: { path: string; kind: "error" | "warning" }) {
  const { errors, warnings } = useForm();
  const list: SpecIssue[] = (kind === "error" ? errors : warnings).byPath.get(path) ?? [];
  if (list.length === 0) return null;
  return (
    <ul className={`fld-issues fld-${kind}`} id={`${kind === "error" ? "err" : "warn"}:${path}`}>
      {list.map((i, n) => (
        <li key={n}>
          <span className="visually-hidden">{kind === "error" ? "Error: " : "Warning: "}</span>
          {i.message}
        </li>
      ))}
    </ul>
  );
}

function Notes({ field, path, indices }: { field: SpecField; path: string; indices: Seg[] }) {
  const { data, crossNotes, warnings } = useForm();
  const own = (field.notes ?? []).filter((n) => !n.when || evalCond(n.when, data, indices));
  const cross = crossNotes.filter(
    (n) =>
      n.paths.includes(schemaPathOf(path)) &&
      (!n.when || evalCond(n.when, data, indices)) &&
      !(n.level === "warning" && warnings.byPath.has(path)),
  );
  if (own.length + cross.length === 0) return null;
  return (
    <ul className="fld-notes">
      {[...own, ...cross].map((n, i) => (
        <li key={i} className={`fld-note fld-note-${n.level}`}>
          {n.text}
        </li>
      ))}
    </ul>
  );
}

function useRequired(field: SpecField, indices: Seg[]): boolean {
  const { data } = useForm();
  return !!field.required || (!!field.required_if && evalCond(field.required_if, data, indices));
}

function Label({ field, path, required, plain = false }: { field: SpecField; path: string; required: boolean; plain?: boolean }) {
  const text = (
    <>
      {label(field)}
      {required && (
        <span className="fld-req" aria-hidden="true">
          {" "}
          *
        </span>
      )}
    </>
  );
  return (
    <div className="fld-labelrow">
      {plain ? (
        <span className="fld-label">{text}</span>
      ) : (
        <label className="fld-label" htmlFor={inputId(path)}>
          {text}
        </label>
      )}
      {isGeneric(field) && (
        <span className="fld-tag" title="No custom form metadata: rendered with a generic widget">
          generic
        </span>
      )}
      <code className="fld-path">{path}</code>
    </div>
  );
}

function Reset({ path, field }: { path: string; field: SpecField }) {
  const { data, set, readOnly } = useForm();
  const present = getAt(data, splitPath(path)) !== undefined;
  if (readOnly || !present || field.required) return null;
  return (
    <button type="button" className="fld-reset" onClick={() => set(path, undefined)} title="Remove this value (use the default)">
      reset
    </button>
  );
}

function Shell({
  field,
  path,
  indices,
  children,
  inline = false,
}: {
  field: SpecField;
  path: string;
  indices: Seg[];
  children: ReactNode;
  inline?: boolean;
}) {
  const { errors } = useForm();
  const required = useRequired(field, indices);
  const invalid = (errors.byPath.get(path)?.length ?? 0) > 0;
  return (
    <div className={`fld${invalid ? " fld-invalid" : ""}${inline ? " fld-inline" : ""}`} id={fieldId(path)} data-path={path}>
      <Label field={field} path={path} required={required} />
      <div className="fld-control">{children}</div>
      {field.help && <div className="fld-help" id={`help:${path}`}>{field.help}</div>}
      <Notes field={field} path={path} indices={indices} />
      <Issues path={path} kind="error" />
      <Issues path={path} kind="warning" />
      <Reset path={path} field={field} />
    </div>
  );
}

function describedBy(path: string, hasHelp: boolean, errors: boolean) {
  return [hasHelp ? `help:${path}` : "", errors ? `err:${path}` : ""].filter(Boolean).join(" ") || undefined;
}

// ---------- scalar widgets ----------

function useScalar(path: string) {
  const { data, set, readOnly, errors } = useForm();
  return {
    value: getAt(data, splitPath(path)),
    set: (v: Json) => set(path, v),
    readOnly,
    invalid: (errors.byPath.get(path)?.length ?? 0) > 0,
  };
}

function TextWidget({ field, path, indices, multiline }: FieldProps & { multiline?: boolean }) {
  const { value, set, readOnly, invalid } = useScalar(path);
  const listId = useId();
  const common = {
    id: inputId(path),
    className: "field fld-input",
    value: typeof value === "string" ? value : value == null ? "" : JSON.stringify(value),
    placeholder: field.placeholder ?? (typeof field.default === "string" ? field.default : undefined),
    readOnly,
    "aria-invalid": invalid || undefined,
    "aria-describedby": describedBy(path, !!field.help, invalid),
    onChange: (e: { target: { value: string } }) => set(e.target.value === "" ? undefined : e.target.value),
  };
  return (
    <Shell field={field} path={path} indices={indices}>
      {multiline ? (
        <textarea {...common} rows={4} spellCheck={false} />
      ) : (
        <>
          <input {...common} type="text" spellCheck={false} autoComplete="off" list={field.suggestions?.length ? listId : undefined} />
          {field.suggestions?.length ? (
            <datalist id={listId}>
              {field.suggestions.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          ) : null}
        </>
      )}
    </Shell>
  );
}

function parseNum(text: string): number | undefined {
  if (text.trim() === "") return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

function NumberWidget({ field, path, indices }: FieldProps) {
  const { value, set, readOnly, invalid } = useScalar(path);
  const num = typeof value === "number" ? value : undefined;
  const [text, setText] = useState(num === undefined ? "" : String(num));
  const [prev, setPrev] = useState(num);
  if (num !== prev) {
    setPrev(num);
    if (parseNum(text) !== num) setText(num === undefined ? "" : String(num));
  }
  const integer = field.kind === "integer";
  const min = field.min ?? field.exclusive_min;
  return (
    <Shell field={field} path={path} indices={indices}>
      <input
        id={inputId(path)}
        className="field fld-input fld-num"
        type="number"
        inputMode={integer ? "numeric" : "decimal"}
        step={integer ? 1 : "any"}
        min={min}
        max={field.max ?? field.exclusive_max}
        value={text}
        placeholder={field.default != null && typeof field.default !== "object" ? String(field.default) : undefined}
        readOnly={readOnly}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy(path, !!field.help, invalid)}
        onChange={(e) => {
          setText(e.target.value);
          const n = parseNum(e.target.value);
          if (e.target.value.trim() === "") set(undefined);
          else if (n !== undefined) set(n);
        }}
      />
      {field.unit && <span className="fld-unit">{field.unit}</span>}
    </Shell>
  );
}

function SelectWidget({ field, path, indices }: FieldProps) {
  const { value, set, readOnly, invalid } = useScalar(path);
  const options = field.options ?? [];
  const required = useRequired(field, indices);
  if (field.multiple) {
    const chosen = Array.isArray(value) ? value : [];
    const toggle = (o: unknown) => {
      const has = chosen.includes(o);
      const next = options.filter((x) => (x === o ? !has : chosen.includes(x)));
      set(next.length === 0 && !field.required ? undefined : next);
    };
    return (
      <div className={`fld${invalid ? " fld-invalid" : ""}`} id={fieldId(path)} data-path={path}>
        <Label field={field} path={path} required={required} plain />
        <div className="fld-control fld-chips" role="group" aria-label={label(field)}>
          {options.map((o, i) => (
            <label key={String(o)} className={`chip${chosen.includes(o) ? " chip-on" : ""}`}>
              <input
                id={i === 0 ? `${inputId(path)}:0` : undefined}
                type="checkbox"
                checked={chosen.includes(o)}
                disabled={readOnly}
                onChange={() => toggle(o)}
              />
              <span>{String(o)}</span>
            </label>
          ))}
        </div>
        {field.help && <div className="fld-help">{field.help}</div>}
        <Notes field={field} path={path} indices={indices} />
        <Issues path={path} kind="error" />
        <Issues path={path} kind="warning" />
      </div>
    );
  }
  const idx = options.findIndex((o) => o === value);
  return (
    <Shell field={field} path={path} indices={indices}>
      <select
        id={inputId(path)}
        className="field fld-input"
        value={idx >= 0 ? String(idx) : ""}
        disabled={readOnly}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy(path, !!field.help, invalid)}
        onChange={(e) => set(e.target.value === "" ? undefined : options[Number(e.target.value)])}
      >
        {(!required || idx < 0) && (
          <option value="">{field.default != null ? `(default: ${String(field.default)})` : "(not set)"}</option>
        )}
        {options.map((o, i) => (
          <option key={String(o)} value={String(i)}>
            {String(o)}
          </option>
        ))}
      </select>
    </Shell>
  );
}

function CheckboxWidget({ field, path, indices }: FieldProps) {
  const { value, set, readOnly, invalid } = useScalar(path);
  const shown = typeof value === "boolean" ? value : field.default === true;
  const set_ = value !== undefined;
  return (
    <div className={`fld fld-check${invalid ? " fld-invalid" : ""}`} id={fieldId(path)} data-path={path}>
      <div className="fld-control">
        <label className="fld-checklabel">
          <input
            id={inputId(path)}
            type="checkbox"
            checked={shown}
            disabled={readOnly}
            aria-describedby={describedBy(path, !!field.help, invalid)}
            onChange={(e) => set(e.target.checked)}
          />
          <span className="fld-label">{label(field)}</span>
          {!set_ && <span className="fld-tag">default</span>}
          {isGeneric(field) && <span className="fld-tag">generic</span>}
          <code className="fld-path">{path}</code>
        </label>
      </div>
      {field.help && <div className="fld-help" id={`help:${path}`}>{field.help}</div>}
      <Notes field={field} path={path} indices={indices} />
      <Issues path={path} kind="error" />
      <Issues path={path} kind="warning" />
      <Reset path={path} field={field} />
    </div>
  );
}

function PathWidget({ field, path, indices }: FieldProps) {
  const { value, set, readOnly, invalid } = useScalar(path);
  const listId = useId();
  const text = typeof value === "string" ? value : "";
  const [focused, setFocused] = useState(false);
  const q = useDebounced(text.replace(/^(\.\.\/)+/, "").replace(/^\.\//, ""), 250);
  const [sugg, setSugg] = useState<SpecPathSuggestion[]>([]);
  const absolute = field.relative_to === "absolute";
  useEffect(() => {
    if (!focused || absolute) return;
    const ctl = new AbortController();
    specsApi
      .paths(q, ctl.signal)
      .then((r) => !ctl.signal.aborted && setSugg(r.paths ?? []))
      .catch(() => undefined);
    return () => ctl.abort();
  }, [q, focused, absolute]);
  const shown = useMemo(
    () => sugg.filter((s) => !field.path_kind || field.path_kind === "file_or_dir" || s.kind === field.path_kind).slice(0, 40),
    [sugg, field.path_kind],
  );
  return (
    <Shell field={field} path={path} indices={indices}>
      <input
        id={inputId(path)}
        className="field fld-input mono"
        type="text"
        spellCheck={false}
        autoComplete="off"
        value={text}
        readOnly={readOnly}
        placeholder={field.placeholder ?? (field.relative_to === "spec_file" ? "../../fixtures/..." : undefined)}
        list={absolute ? undefined : listId}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy(path, !!field.help, invalid)}
        onFocus={() => setFocused(true)}
        onChange={(e) => set(e.target.value === "" ? undefined : e.target.value)}
      />
      {!absolute && (
        <datalist id={listId}>
          {shown.map((s) => (
            <option key={s.value} value={s.value} label={s.repo_path} />
          ))}
        </datalist>
      )}
      {field.path_kind && <span className="fld-unit">{field.path_kind.replace(/_/g, " ")}</span>}
    </Shell>
  );
}

// ---------- JSON (generic fallback) ----------

export function JsonText({
  id,
  value,
  onValid,
  readOnly,
  rows = 5,
  invalid,
}: {
  id?: string;
  value: Json;
  onValid: (v: Json) => void;
  readOnly: boolean;
  rows?: number;
  invalid?: boolean;
}) {
  const fmt = (v: Json) => (v === undefined ? "" : JSON.stringify(v, null, 2));
  const [text, setText] = useState(fmt(value));
  const [prev, setPrev] = useState(JSON.stringify(value));
  const [err, setErr] = useState<string | null>(null);
  const cur = JSON.stringify(value);
  if (cur !== prev) {
    setPrev(cur);
    let same: boolean;
    try {
      same = text.trim() !== "" && JSON.stringify(JSON.parse(text)) === cur;
    } catch {
      same = false;
    }
    if (!same) {
      setText(fmt(value));
      setErr(null);
    }
  }
  return (
    <>
      <textarea
        id={id}
        className="field fld-input mono fld-json"
        rows={rows}
        spellCheck={false}
        value={text}
        readOnly={readOnly}
        aria-invalid={invalid || !!err || undefined}
        onChange={(e) => {
          const t = e.target.value;
          setText(t);
          if (t.trim() === "") {
            setErr(null);
            onValid(undefined);
            return;
          }
          try {
            onValid(JSON.parse(t));
            setErr(null);
          } catch (x) {
            setErr(x instanceof Error ? x.message : "invalid JSON");
          }
        }}
      />
      {err && (
        <div className="fld-issues fld-error" role="alert">
          Not valid JSON yet (the value is not applied): {err}
        </div>
      )}
    </>
  );
}

function JsonWidget({ field, path, indices }: FieldProps) {
  const { value, set, readOnly, invalid } = useScalar(path);
  return (
    <Shell field={field} path={path} indices={indices}>
      <JsonText id={inputId(path)} value={value} onValid={set} readOnly={readOnly} invalid={invalid} />
    </Shell>
  );
}

// ---------- lists ----------

function StringListWidget({ field, path, indices }: FieldProps) {
  const { value, set, readOnly } = useScalar(path);
  const items: string[] = Array.isArray(value) ? value.map((x) => (typeof x === "string" ? x : JSON.stringify(x))) : [];
  const write = (next: string[]) => set(next.length === 0 && !field.required ? undefined : next);
  const focusRow = (i: number) =>
    requestAnimationFrame(() => document.getElementById(`${inputId(path)}:${i}`)?.focus());
  return (
    <Shell field={field} path={path} indices={indices}>
      <div className="listw">
        {items.length === 0 && <div className="muted fld-empty">None</div>}
        {items.map((it, i) => (
          <div className="listw-row" key={i}>
            <input
              id={`${inputId(path)}:${i}`}
              className="field fld-input"
              aria-label={`${label(field)} ${i + 1}`}
              value={it}
              readOnly={readOnly}
              placeholder={field.item_hint}
              spellCheck={false}
              onChange={(e) => write(items.map((x, j) => (j === i ? e.target.value : x)))}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !readOnly) {
                  e.preventDefault();
                  set([...items.slice(0, i + 1), "", ...items.slice(i + 1)]);
                  focusRow(i + 1);
                }
              }}
            />
            {!readOnly && (
              <span className="listw-btns">
                <button type="button" className="icon-btn" aria-label={`Move ${label(field)} ${i + 1} up`} disabled={i === 0} onClick={() => set(moveItem(items, i, i - 1))}>
                  ↑
                </button>
                <button type="button" className="icon-btn" aria-label={`Move ${label(field)} ${i + 1} down`} disabled={i === items.length - 1} onClick={() => set(moveItem(items, i, i + 1))}>
                  ↓
                </button>
                <button type="button" className="icon-btn" aria-label={`Remove ${label(field)} ${i + 1}`} onClick={() => write(items.filter((_, j) => j !== i))}>
                  ✕
                </button>
              </span>
            )}
          </div>
        ))}
        {!readOnly && (
          <button
            type="button"
            className="btn btn-small"
            onClick={() => {
              set([...items, ""]);
              focusRow(items.length);
            }}
          >
            + Add
          </button>
        )}
      </div>
    </Shell>
  );
}

function ObjectListWidget({ field, path, indices }: FieldProps) {
  const { value, set, readOnly } = useScalar(path);
  const rows: Json[] = Array.isArray(value) ? value : [];
  const f = useForm();
  const write = (next: Json[]) => set(next.length === 0 && !field.required ? undefined : next);
  const own = issuesUnder(f.errors, path);
  return (
    <div className={`fld fld-group${own ? " fld-invalid" : ""}`} id={fieldId(path)} data-path={path}>
      <div className="fld-grouphead">
        <Label field={field} path={path} required={!!field.required} plain />
        {own > 0 && <span className="count-bad">{own} issue{own === 1 ? "" : "s"}</span>}
      </div>
      {field.help && <div className="fld-help">{field.help}</div>}
      <Issues path={path} kind="error" />
      <div className="rows">
        {rows.length === 0 && <div className="muted fld-empty">None</div>}
        {rows.map((_, i) => (
          <fieldset className="row-card" key={i} data-row={joinPath(path, i)} id={fieldId(joinPath(path, i))}>
            <legend>
              {label(field)} #{i + 1}
            </legend>
            {!readOnly && (
              <span className="row-btns">
                <button type="button" className="icon-btn" aria-label={`Move ${label(field)} ${i + 1} up`} disabled={i === 0} onClick={() => set(moveItem(rows, i, i - 1))}>
                  ↑
                </button>
                <button type="button" className="icon-btn" aria-label={`Move ${label(field)} ${i + 1} down`} disabled={i === rows.length - 1} onClick={() => set(moveItem(rows, i, i + 1))}>
                  ↓
                </button>
                <button type="button" className="icon-btn" aria-label={`Remove ${label(field)} ${i + 1}`} onClick={() => write(rows.filter((_, j) => j !== i))}>
                  ✕
                </button>
              </span>
            )}
            <FieldList fields={ownChildren(field)} base={joinPath(path, i)} indices={[...indices, i]} inAdvanced />
          </fieldset>
        ))}
      </div>
      {!readOnly && (
        <button id={`${inputId(path)}:add`} type="button" className="btn btn-small" onClick={() => write([...rows, {}])}>
          + Add {label(field).toLowerCase()}
        </button>
      )}
    </div>
  );
}

// ---------- objects ----------

function ObjectWidget({ field, path, indices, bare, inAdvanced }: FieldProps) {
  const f = useForm();
  const value = getAt(f.data, splitPath(path));
  const present = isObj(value);
  const optionalAbsent = !present && !field.required && field.default == null;
  const own = issuesUnder(f.errors, path);
  const kids = ownChildren(field);

  if (bare) {
    return (
      <div className="obj-bare" id={fieldId(path)} data-path={path}>
        <Issues path={path} kind="error" />
        <FieldList fields={kids} base={path} indices={indices} inAdvanced={inAdvanced} />
      </div>
    );
  }
  return (
    <fieldset className={`obj${own ? " fld-invalid" : ""}`} id={fieldId(path)} data-path={path}>
      <legend>
        <span className="fld-label">{label(field)}</span>
        {isGeneric(field) && <span className="fld-tag">generic</span>}
        <code className="fld-path">{path}</code>
        {own > 0 && <span className="count-bad">{own} issue{own === 1 ? "" : "s"}</span>}
      </legend>
      {field.help && <div className="fld-help">{field.help}</div>}
      <Issues path={path} kind="error" />
      {optionalAbsent ? (
        <div className="obj-absent">
          <span className="muted">Not set.</span>
          {!f.readOnly && (
            <button type="button" className="btn btn-small" onClick={() => f.set(path, {})}>
              + Add {label(field).toLowerCase()}
            </button>
          )}
        </div>
      ) : (
        <>
          <FieldList fields={kids} base={path} indices={indices} inAdvanced={inAdvanced || !!field.advanced} />
          {present && !field.required && field.default == null && !f.readOnly && (
            <button type="button" className="fld-reset" onClick={() => f.set(path, undefined)}>
              remove {label(field).toLowerCase()}
            </button>
          )}
        </>
      )}
    </fieldset>
  );
}

// ---------- dispatch ----------

export function FieldRenderer(props: FieldProps) {
  const { data } = useForm();
  const { field, indices } = props;
  if (field.visible_if && !evalCond(field.visible_if, data, indices)) return null;
  switch (resolveWidget(field)) {
    case "textarea":
      return <TextWidget {...props} multiline />;
    case "number":
      return <NumberWidget {...props} />;
    case "select":
      return <SelectWidget {...props} />;
    case "checkbox":
      return <CheckboxWidget {...props} />;
    case "path":
      return <PathWidget {...props} />;
    case "string_list":
      return <StringListWidget {...props} />;
    case "object":
      return <ObjectWidget {...props} />;
    case "object_list":
      return <ObjectListWidget {...props} />;
    case "json":
      return <JsonWidget {...props} />;
    default:
      return <TextWidget {...props} />;
  }
}

/** Fields of one container: normal ones first, then one collapsible "Advanced" group. */
export function FieldList({
  fields,
  base,
  indices,
  inAdvanced = false,
  bareRoots = false,
}: {
  fields: SpecField[];
  base: string;
  indices: Seg[];
  inAdvanced?: boolean;
  /** Section level: a lone object root is rendered without its own box. */
  bareRoots?: boolean;
}) {
  const { data, errors, open, setOpen } = useForm();
  const shown = fields.filter((f) => !f.visible_if || evalCond(f.visible_if, data, indices));
  const render = (f: SpecField) => {
    const path = bareRoots ? f.path : joinPath(base, f.key);
    return (
      <FieldRenderer
        key={f.key}
        field={f}
        path={path}
        indices={indices}
        inAdvanced={inAdvanced}
        bare={bareRoots && shown.length === 1 && f.kind === "object" && !!f.fields}
      />
    );
  };
  const normal = shown.filter((f) => inAdvanced || !f.advanced);
  const adv = shown.filter((f) => !inAdvanced && f.advanced);
  // nothing but advanced fields: show them, a lone collapsed "Advanced" panel would hide the whole container
  if (normal.length === 0) return <>{adv.map(render)}</>;
  const key = `adv:${base}`;
  const advIssues = adv.reduce((n, f) => n + issuesUnder(errors, bareRoots ? f.path : joinPath(base, f.key)), 0);
  const isOpen = open.has(key) || advIssues > 0;
  return (
    <>
      {normal.map(render)}
      {adv.length > 0 && (
        <div className="adv">
          <button
            type="button"
            className="adv-toggle"
            aria-expanded={isOpen}
            onClick={() => setOpen(key, !isOpen)}
          >
            <span aria-hidden="true">{isOpen ? "▾" : "▸"}</span> Advanced ({adv.length})
            {advIssues > 0 && <span className="count-bad">{advIssues} issue{advIssues === 1 ? "" : "s"}</span>}
          </button>
          {isOpen && <div className="adv-body">{adv.map(render)}</div>}
        </div>
      )}
    </>
  );
}

/** A data key the schema does not know: edit it as JSON, or remove it, so nothing is silently dropped. */
export function ExtraField({ path }: { path: string }) {
  const { data, set, readOnly } = useForm();
  const value = getAt(data, splitPath(path));
  return (
    <div className="fld" id={fieldId(path)} data-path={path}>
      <div className="fld-labelrow">
        <label className="fld-label" htmlFor={inputId(path)}>
          {path}
        </label>
        <span className="fld-tag">unknown to the schema</span>
      </div>
      <div className="fld-control">
        <JsonText id={inputId(path)} value={value} onValid={(v) => set(path, v)} readOnly={readOnly} />
      </div>
      <Issues path={path} kind="error" />
      {!readOnly && (
        <button type="button" className="fld-reset" onClick={() => set(path, undefined)}>
          remove
        </button>
      )}
    </div>
  );
}
