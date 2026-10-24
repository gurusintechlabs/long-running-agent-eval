import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ApiError,
  specsApi,
  useAsync,
  type SpecData,
  type SpecInput,
  type SpecSchema,
  type SpecValidation,
} from "../../api";
import { Badge, Card, ConfirmDialog, ErrorState, Spinner } from "../../components";
import { formatUsd } from "../../lib/format";
import { SpecForm, blockIssueCount } from "./SpecForm";
import { indexIssues, revealKeys, sameData, sectionBlocks, fieldId, inputId } from "./formLogic";
import { useUnsavedGuard } from "./useUnsavedGuard";
import { parseYaml, toYaml } from "./yamlio";
import "./specs.css";

export const NAME_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
export function nameProblem(n: string): string | null {
  if (!n) return "Enter a name for the draft.";
  if (!NAME_RE.test(n) || n.endsWith(".")) return "Use lowercase letters, digits, '.', '_' or '-' (max 64, start with a letter or digit).";
  if (["schema", "validate", "save", "paths"].includes(n)) return `"${n}" is reserved.`;
  return null;
}

type Source = "draft" | "example" | "new";
interface Loaded {
  name: string | null;
  source: Source;
  data: SpecData;
  validation: SpecValidation | null;
  mtime: number | null;
}

const storeKey = (source: Source, name: string | null) => `lrae.specedit:${source}:${name ?? "_new"}`;
function readStore(key: string): SpecData | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as SpecData) : null;
  } catch {
    return null;
  }
}
function writeStore(key: string, data: SpecData | null) {
  try {
    if (data) window.sessionStorage.setItem(key, JSON.stringify(data));
    else window.sessionStorage.removeItem(key);
  } catch {
    /* storage can be unavailable: the unsaved-changes prompt still works */
  }
}

// ---------- route component ----------

export function SpecEditorPage() {
  const { name = "" } = useParams();
  const [sp] = useSearchParams();
  const isNew = name === "_new";
  const source: Source = isNew ? "new" : sp.get("source") === "example" ? "example" : "draft";
  const schemaQ = useAsync((s) => specsApi.schema(s), []);
  const specQ = useAsync<Loaded>(
    async (s) => {
      if (isNew) return { name: null, source: "new", data: {}, validation: null, mtime: null };
      const d = await specsApi.get(name, source === "example" ? "example" : "draft", s);
      return { name: d.name, source: d.source, data: d.data, validation: d.validation, mtime: d.mtime };
    },
    [name, source],
  );

  useEffect(() => {
    document.title = `${isNew ? "New spec" : name} · Specs · LRAE`;
  }, [name, isNew]);

  if (schemaQ.error || specQ.error) {
    return (
      <>
        <BackLink />
        <ErrorState
          title={specQ.error instanceof ApiError && specQ.error.status === 404 ? "No such spec" : "Cannot load the spec editor"}
          error={specQ.error ?? schemaQ.error}
          onRetry={() => {
            schemaQ.reload();
            specQ.reload();
          }}
        />
      </>
    );
  }
  // useAsync keeps the previous result for one render after the route changes: only show data for this route
  const fresh = specQ.data && (isNew ? specQ.data.source === "new" : specQ.data.name === name && specQ.data.source === source);
  if (!schemaQ.data || !specQ.data || !fresh) return <Spinner label="Loading spec" />;
  return <SpecEditor key={`${source}:${name}`} schema={schemaQ.data} init={specQ.data} />;
}

function BackLink() {
  return (
    <div className="crumbs">
      <Link to="/specs">← Specs</Link>
    </div>
  );
}

// ---------- editor ----------

type Tab = "form" | "yaml";

export function SpecEditor({ schema, init }: { schema: SpecSchema; init: Loaded }) {
  const navigate = useNavigate();
  const location = useLocation();
  const key = storeKey(init.source, init.name);
  const [savedData, setSavedData] = useState<SpecData>(init.data);
  const [restored, setRestored] = useState(false);
  const [data, setData] = useState<SpecData>(() => {
    const stored = readStore(key);
    return stored && !sameData(stored, init.data) ? stored : init.data;
  });
  const [open, setOpenSet] = useState<ReadonlySet<string>>(new Set());
  const [tab, setTab] = useState<Tab>("form");
  const [yamlEdit, setYamlEdit] = useState(false);
  const [yamlText, setYamlText] = useState("");
  const [yamlError, setYamlError] = useState<string | null>(null);
  const [preview, setPreview] = useState("");
  const [draftName, setDraftName] = useState(init.source === "example" && init.name ? `${init.name}-edit` : "");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(
    (location.state as { saved?: boolean } | null)?.saved ? { tone: "ok", text: "Saved." } : null,
  );
  const [confirm, setConfirm] = useState<null | "overwrite" | "discard">(null);
  const [savedName, setSavedName] = useState<string | null>(init.source === "draft" ? init.name : null);
  const readOnly = false;

  const dirty = !sameData(data, savedData);
  useUnsavedGuard(dirty);

  useEffect(() => {
    // restored banner: only when the stored copy actually differs from the file
    const stored = readStore(key);
    if (stored && !sameData(stored, init.data) && sameData(stored, data)) setRestored(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    writeStore(key, dirty ? data : null);
  }, [dirty, data, key]);

  const edit = useCallback((fn: (d: SpecData) => SpecData) => setData((d) => fn(d)), []);
  const setOpen = useCallback(
    (k: string, v: boolean) =>
      setOpenSet((prev) => {
        const n = new Set(prev);
        if (v) n.add(k);
        else n.delete(k);
        return n;
      }),
    [],
  );

  // ----- live validation -----
  const payload: SpecInput | null = yamlEdit ? (yamlError ? null : { yaml: yamlText }) : { data };
  const vKey = payload ? JSON.stringify(payload) : "";
  const [res, setRes] = useState<{ key: string; v?: SpecValidation; err?: string } | null>(
    init.validation ? { key: JSON.stringify({ data: init.data }), v: init.validation } : null,
  );
  const latest = useRef("");
  const runValidate = useCallback(async (k: string, p: SpecInput) => {
    latest.current = k;
    try {
      const v = await specsApi.validate(p);
      if (latest.current === k) setRes({ key: k, v });
    } catch (e) {
      if (latest.current === k) setRes({ key: k, err: e instanceof Error ? e.message : "validation failed" });
    }
  }, []);
  useEffect(() => {
    if (!payload || res?.key === vKey) return;
    latest.current = vKey;
    const t = setTimeout(() => void runValidate(vKey, payload), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vKey]);

  const validation = res?.v ?? null;
  const pending = !!payload && res?.key !== vKey;
  const errIdx = useMemo(() => indexIssues(validation?.errors ?? []), [validation]);
  const warnIdx = useMemo(() => indexIssues(validation?.warnings ?? []), [validation]);
  const blocks = useMemo(() => sectionBlocks(schema), [schema]);

  // ----- jump to a field -----
  const [revealTick, setRevealTick] = useState(0);
  const target = useRef<string | null>(null);
  const reveal = useCallback(
    (path: string) => {
      target.current = path;
      setOpenSet((prev) => new Set([...prev, ...revealKeys(schema, path), "adv:"]));
      setTab("form");
      setRevealTick((t) => t + 1);
    },
    [schema],
  );
  useEffect(() => {
    const path = target.current;
    if (!path) return;
    target.current = null;
    const segs = path.split(".");
    for (let n = segs.length; n >= 1; n--) {
      const p = segs.slice(0, n).join(".");
      const el = document.getElementById(inputId(p)) ?? document.getElementById(fieldId(p));
      if (el) {
        (el.matches("input,select,textarea,button") ? el : el.querySelector<HTMLElement>("input,select,textarea,button") ?? el).focus?.({ preventScroll: true });
        el.scrollIntoView?.({ block: "center", behavior: "smooth" });
        return;
      }
    }
  }, [revealTick]);

  const gotoSection = (id: string) => {
    setOpen(`sec:${id}`, true);
    setTab("form");
    requestAnimationFrame(() => document.getElementById(`sec-${id}`)?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
  };

  // ----- YAML tab -----
  useEffect(() => {
    if (tab !== "yaml" || yamlEdit) return;
    let alive = true;
    void toYaml(data).then((t) => alive && setPreview(t));
    return () => {
      alive = false;
    };
  }, [tab, yamlEdit, data]);

  const yamlLatest = useRef("");
  const onYamlChange = (t: string) => {
    setYamlText(t);
    yamlLatest.current = t;
    void parseYaml(t).then((r) => {
      if (yamlLatest.current !== t) return;
      if (r.ok) {
        setYamlError(null);
        setData(r.data);
      } else setYamlError(r.error);
    });
  };
  const startYamlEdit = async () => {
    const t = await toYaml(data);
    yamlLatest.current = t;
    setYamlText(t);
    setYamlError(null);
    setYamlEdit(true);
  };
  const stopYamlEdit = () => {
    setYamlEdit(false);
    setYamlError(null);
  };
  const switchTab = (t: Tab) => {
    if (t === "form" && yamlEdit) stopYamlEdit();
    setTab(t);
  };

  // ----- save -----
  const isDraft = savedName !== null;
  const targetName = isDraft ? (savedName as string) : draftName.trim();
  const problem = isDraft ? null : nameProblem(targetName);
  const canSave = !saving && !problem && !yamlError && (dirty || !isDraft);

  const doSave = useCallback(
    async (overwrite: boolean) => {
      setSaving(true);
      setSaveMsg(null);
      try {
        const r = await specsApi.save(targetName, { data }, overwrite);
        setSavedData(data);
        setSavedName(r.name);
        setRes({ key: JSON.stringify({ data }), v: r });
        writeStore(key, null);
        setRestored(false);
        if (!isDraft) navigate(`/specs/${encodeURIComponent(r.name)}?source=draft`, { replace: true, state: { saved: true } });
        else setSaveMsg({ tone: "ok", text: `Saved ${r.path}.` });
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && !overwrite) {
          setConfirm("overwrite");
        } else if (e instanceof ApiError && e.status === 422 && e.body && typeof e.body === "object") {
          setRes({ key: JSON.stringify({ data }), v: e.body as SpecValidation });
          setSaveMsg({ tone: "bad", text: "Not saved: the spec has errors." });
        } else {
          setSaveMsg({ tone: "bad", text: e instanceof Error ? e.message : "save failed" });
        }
      } finally {
        setSaving(false);
      }
    },
    [targetName, data, key, isDraft, navigate],
  );

  const requestSave = useCallback(() => {
    if (!canSave) return;
    if (isDraft) setConfirm("overwrite");
    else void doSave(false);
  }, [canSave, isDraft, doSave]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        requestSave();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [requestSave]);

  const discard = () => {
    setData(savedData);
    writeStore(key, null);
    setRestored(false);
    setYamlEdit(false);
    setYamlError(null);
    setConfirm(null);
  };

  const errCount = validation?.errors.length ?? 0;
  const warnCount = validation?.warnings.length ?? 0;
  const ok = validation?.valid && !pending;
  const title = init.source === "new" ? "New spec" : (init.name ?? "");

  return (
    <div className="spec-editor">
      <BackLink />
      <div className="se-bar" role="region" aria-label="Spec actions">
        <div className="se-bar-main">
          <h1 className="se-title">{title}</h1>
          <Badge tone={init.source === "example" && !isDraft ? "info" : "neutral"} plain>
            {isDraft ? "draft" : init.source === "example" ? "from example" : "new"}
          </Badge>
          {dirty && <Badge tone="warn">unsaved changes</Badge>}
          <span className="se-status" role="status" aria-live="polite">
            {pending ? (
              <span className="muted">Validating…</span>
            ) : res?.err ? (
              <Badge tone="bad">validation failed</Badge>
            ) : yamlError ? (
              <Badge tone="bad">YAML error</Badge>
            ) : validation ? (
              validation.valid ? (
                <Badge tone="ok">valid</Badge>
              ) : (
                <Badge tone="bad">
                  {errCount} error{errCount === 1 ? "" : "s"}
                </Badge>
              )
            ) : (
              <span className="muted">Not validated yet</span>
            )}
            {warnCount > 0 && !pending && (
              <Badge tone="warn">
                {warnCount} warning{warnCount === 1 ? "" : "s"}
              </Badge>
            )}
          </span>
        </div>
        <div className="se-bar-actions">
          {!isDraft && (
            <label className="se-name">
              <span className="visually-hidden">Draft name</span>
              <input
                className="field"
                placeholder="draft name, e.g. my-spec"
                value={draftName}
                aria-invalid={!!draftName && !!problem}
                onChange={(e) => setDraftName(e.target.value)}
              />
            </label>
          )}
          <button type="button" className="btn" disabled={!payload} onClick={() => payload && void runValidate(vKey, payload)}>
            Validate
          </button>
          {dirty && (
            <button type="button" className="btn" onClick={() => setConfirm("discard")}>
              Discard changes
            </button>
          )}
          <button type="button" className="btn btn-primary" disabled={!canSave} onClick={requestSave} title={problem ?? "Save to spec/drafts (Ctrl/Cmd+S)"}>
            {saving ? "Saving…" : isDraft ? "Save" : "Save as draft"}
          </button>
          {isDraft && !dirty && validation?.valid ? (
            <Link className="btn" to={`/launch?spec=${encodeURIComponent(savedName as string)}`}>
              Launch this draft →
            </Link>
          ) : (
            <button type="button" className="btn" disabled title={isDraft ? "Save a valid spec first" : "Save as a draft first"}>
              Launch →
            </button>
          )}
        </div>
      </div>

      {init.source === "example" && !isDraft && (
        <div className="banner banner-info">
          This is an example (read-only file). Your edits stay in the browser until you save them as a new draft under the name above;
          to keep the file's comments, use “Duplicate to draft” in the <Link to="/specs">Specs list</Link> instead.
        </div>
      )}
      {restored && (
        <div className="banner banner-warn">
          Restored unsaved edits from earlier in this browser session.{" "}
          <button type="button" className="link-btn" onClick={discard}>
            Discard them
          </button>
        </div>
      )}
      {saveMsg && (
        <div className={`banner banner-${saveMsg.tone === "ok" ? "ok" : "bad"}`} role="status">
          {saveMsg.text}
          {saveMsg.tone === "ok" && isDraft && (
            <>
              {" "}
              <Link to={`/launch?spec=${encodeURIComponent(savedName as string)}`}>Open in Launch →</Link>
            </>
          )}
        </div>
      )}
      {!isDraft && draftName && problem && <div className="banner banner-bad">{problem}</div>}

      <ValidationSummary validation={validation} stale={pending} fetchError={res?.err} yamlError={yamlError} onJump={reveal} />

      <div className="se-tabs" role="tablist" aria-label="Editor view">
        <button type="button" role="tab" aria-selected={tab === "form"} className={tab === "form" ? "tab on" : "tab"} onClick={() => switchTab("form")}>
          Form
        </button>
        <button type="button" role="tab" aria-selected={tab === "yaml"} className={tab === "yaml" ? "tab on" : "tab"} onClick={() => switchTab("yaml")}>
          YAML
        </button>
      </div>

      {tab === "form" ? (
        <div className="se-layout">
          <nav className="se-nav" aria-label="Sections">
            <ul>
              {blocks.map((b) => {
                const n = blockIssueCount(b, errIdx);
                return (
                  <li key={b.section.id}>
                    <button type="button" className="se-nav-btn" onClick={() => gotoSection(b.section.id)}>
                      <span>{b.section.label}</span>
                      {n > 0 && <span className="count-bad" aria-label={`${n} issues`}>{n}</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className="se-form">
            <SpecForm schema={schema} data={data} edit={edit} readOnly={readOnly} errors={errIdx} warnings={warnIdx} open={open} setOpen={setOpen} />
          </div>
        </div>
      ) : (
        <Card
          title="Spec as YAML"
          actions={
            yamlEdit ? (
              <button type="button" className="btn btn-small" onClick={stopYamlEdit}>
                Done (back to preview)
              </button>
            ) : (
              <button type="button" className="btn btn-small" onClick={() => void startYamlEdit()}>
                Edit as YAML
              </button>
            )
          }
        >
          <p className="muted yaml-note">
            {yamlEdit
              ? "Edits are validated by the same endpoint as the form and are applied to the form as soon as the YAML parses, so you can switch back at any time."
              : "Generated from the form. The saved file is written by the server (schema key order, no comments), so its formatting can differ slightly."}
          </p>
          {yamlEdit ? (
            <>
              <textarea
                className="field yaml-area mono"
                aria-label="Spec YAML"
                spellCheck={false}
                value={yamlText}
                onChange={(e) => onYamlChange(e.target.value)}
              />
              {yamlError && (
                <div className="fld-issues fld-error" role="alert">
                  YAML error: {yamlError}
                </div>
              )}
            </>
          ) : (
            <pre className="yaml-pre" aria-label="Generated YAML" tabIndex={0}>
              {preview}
            </pre>
          )}
        </Card>
      )}

      {ok && validation && <ValidResult v={validation} />}

      {confirm === "overwrite" && (
        <ConfirmDialog
          title={isDraft ? "Overwrite this draft?" : "A draft with this name exists"}
          confirmLabel="Overwrite"
          busy={saving}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            setConfirm(null);
            void doSave(true);
          }}
        >
          <p>
            <code>spec/drafts/{targetName}.yaml</code> will be replaced by the form contents. Comments in the file are not kept when saving from the editor.
          </p>
        </ConfirmDialog>
      )}
      {confirm === "discard" && (
        <ConfirmDialog title="Discard unsaved changes?" confirmLabel="Discard" danger onCancel={() => setConfirm(null)} onConfirm={discard}>
          <p>The form goes back to {isDraft ? "the saved draft" : "the loaded spec"}.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}

// ---------- validation panels ----------

function ValidationSummary({
  validation,
  stale,
  fetchError,
  yamlError,
  onJump,
}: {
  validation: SpecValidation | null;
  stale: boolean;
  fetchError?: string;
  yamlError: string | null;
  onJump: (path: string) => void;
}) {
  if (!validation && !fetchError && !yamlError) return null;
  const errors = validation?.errors ?? [];
  const warnings = validation?.warnings ?? [];
  if (errors.length === 0 && warnings.length === 0 && !fetchError && !yamlError) return null;
  return (
    <div className={`vsum${stale ? " vsum-stale" : ""}`}>
      {fetchError && <div className="banner banner-bad">Validation request failed: {fetchError}</div>}
      {yamlError && <div className="banner banner-bad">YAML does not parse: {yamlError}</div>}
      {errors.length > 0 && (
        <section aria-label="Errors">
          <h2 className="vsum-h vsum-bad">
            {errors.length} problem{errors.length === 1 ? "" : "s"} to fix
          </h2>
          <ul className="vsum-list">
            {errors.map((e, i) => (
              <li key={i}>
                <button type="button" className="vsum-item" onClick={() => onJump(e.path)} disabled={!e.path}>
                  <code>{e.path || "(whole spec)"}</code>
                  <span>{e.message}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {warnings.length > 0 && (
        <section aria-label="Warnings">
          <h2 className="vsum-h vsum-warn">
            {warnings.length} warning{warnings.length === 1 ? "" : "s"}
          </h2>
          <ul className="vsum-list">
            {warnings.map((w, i) => (
              <li key={i}>
                <button type="button" className="vsum-item" onClick={() => onJump(w.path)} disabled={!w.path}>
                  <code>{w.path || "(whole spec)"}</code>
                  <span>{w.message}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function ValidResult({ v }: { v: SpecValidation }) {
  const s = v.summary;
  return (
    <Card title="Valid: what this spec will produce" className="valid-card">
      <dl className="kv">
        <dt>Spec hash</dt>
        <dd>
          <code className="hash-full">{v.spec_hash}</code>
        </dd>
        <dt>Run IDs ({v.run_ids.length})</dt>
        <dd>
          <ul className="runid-list">
            {v.run_ids.map((r) => (
              <li key={r}>
                <code>{r}</code>
              </li>
            ))}
          </ul>
        </dd>
        {num(s.checkpoints) !== null && (
          <>
            <dt>Checkpoints</dt>
            <dd>
              {String(s.checkpoints)} per run
              {num(s.duration_min) !== null && ` (${s.duration_min} min, every ${String(s.checkpoint_interval_min)} min)`}
            </dd>
          </>
        )}
        {num(s.per_run_usd) !== null && (
          <>
            <dt>Spend caps</dt>
            <dd>
              {formatUsd(num(s.per_run_usd))} per run, {formatUsd(num(s.experiment_usd))} for the experiment
            </dd>
          </>
        )}
      </dl>
    </Card>
  );
}
