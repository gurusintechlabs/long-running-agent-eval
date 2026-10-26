import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, specsApi, useAsync, type SpecListEntry } from "../../api";
import { Badge, Card, ConfirmDialog, EmptyState, ErrorState, Spinner } from "../../components";
import { formatDateTime } from "../../lib/format";
import { nameProblem } from "./SpecEditor";
import "./specs.css";

type Dialog =
  | { kind: "duplicate"; spec: SpecListEntry }
  | { kind: "from-example" }
  | { kind: "delete"; spec: SpecListEntry }
  | null;

export function isRealSpend(s: SpecListEntry): boolean {
  return s.runtime === "claude_code";
}

export function SpecsView() {
  const navigate = useNavigate();
  const q = useAsync((s) => specsApi.list(s), []);
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [name, setName] = useState("");
  const [exampleName, setExampleName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [overwrite, setOverwrite] = useState(false);

  useEffect(() => {
    document.title = "Specs · LRAE";
  }, []);

  const all = useMemo(() => q.data?.specs ?? [], [q.data]);
  const match = (s: SpecListEntry) => {
    const t = search.trim().toLowerCase();
    return !t || [s.name, s.experiment_id, s.runtime, s.model].some((x) => x?.toLowerCase().includes(t));
  };
  const drafts = all.filter((s) => s.source === "draft" && match(s));
  const examples = all.filter((s) => s.source === "example" && match(s));
  const allExamples = all.filter((s) => s.source === "example");

  const open = (d: Dialog, preset = "") => {
    setErr(null);
    setOverwrite(false);
    setName(preset);
    setDialog(d);
  };
  const close = () => setDialog(null);

  const problem = name ? nameProblem(name.trim()) : "Enter a name.";

  const doDuplicate = async (from: string, source: "draft" | "example") => {
    setBusy(true);
    setErr(null);
    try {
      const r = await specsApi.duplicate(from, name.trim(), source, overwrite);
      close();
      navigate(`/specs/${encodeURIComponent(r.name)}?source=draft`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setErr(`A draft named “${name.trim()}” already exists.`);
        setOverwrite(true);
      } else setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async (s: SpecListEntry) => {
    setBusy(true);
    try {
      await specsApi.remove(s.name);
      close();
      q.reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Specs</h1>
          <div className="page-sub">
            {q.data ? `${all.filter((s) => s.source === "draft").length} drafts, ${allExamples.length} examples` : "Loading specs"}
            {q.data && <> · drafts live in <code>{q.data.drafts_dir}</code></>}
          </div>
        </div>
        <div className="head-actions">
          <button
            type="button"
            className="btn"
            disabled={allExamples.length === 0}
            onClick={() => {
              setExampleName(allExamples[0]?.name ?? "");
              open({ kind: "from-example" }, allExamples[0] ? `${allExamples[0].name}-copy` : "");
            }}
          >
            New from example…
          </button>
          <Link className="btn btn-primary" to="/specs/_new">
            New blank spec
          </Link>
        </div>
      </div>

      {q.loading && <Spinner label="Loading specs" />}
      {q.error && <ErrorState title="Cannot list specs" error={q.error} onRetry={q.reload} />}

      {q.data && (
        <>
          <form className="toolbar spec-search" role="search" onSubmit={(e) => e.preventDefault()}>
            <label className="tb-field tb-grow">
              <span className="visually-hidden">Search specs</span>
              <input className="field" type="search" placeholder="Search name, experiment, model…" value={search} onChange={(e) => setSearch(e.target.value)} />
            </label>
          </form>

          <Card title={`Drafts (${drafts.length})`} flush>
            {drafts.length === 0 ? (
              <EmptyState title={search ? "No draft matches" : "No drafts yet"}>
                {search ? "Clear the search to see all drafts." : "Duplicate an example, or start a blank spec. Drafts are the only specs you can edit and launch from here."}
              </EmptyState>
            ) : (
              <SpecTable
                rows={drafts}
                actions={(s) => (
                  <>
                    <Link className="btn btn-small" to={`/specs/${encodeURIComponent(s.name)}?source=draft`}>
                      Edit
                    </Link>
                    <button type="button" className="btn btn-small" onClick={() => open({ kind: "duplicate", spec: s }, `${s.name}-copy`)}>
                      Duplicate
                    </button>
                    {s.valid && (
                      <Link className="btn btn-small" to={`/launch?spec=${encodeURIComponent(s.name)}`}>
                        Launch
                      </Link>
                    )}
                    <button type="button" className="btn btn-small btn-quiet-danger" onClick={() => open({ kind: "delete", spec: s })}>
                      Delete
                    </button>
                  </>
                )}
              />
            )}
          </Card>

          <Card title={`Examples (${examples.length})`} flush className="spec-examples">
            {examples.length === 0 ? (
              <EmptyState title="No example matches" />
            ) : (
              <SpecTable
                rows={examples}
                actions={(s) => (
                  <>
                    <Link className="btn btn-small" to={`/specs/${encodeURIComponent(s.name)}?source=example`}>
                      View
                    </Link>
                    <button type="button" className="btn btn-small" onClick={() => open({ kind: "duplicate", spec: s }, `${s.name}-copy`)}>
                      Duplicate to draft
                    </button>
                  </>
                )}
              />
            )}
          </Card>
        </>
      )}

      {dialog?.kind === "duplicate" && (
        <ConfirmDialog
          title={`Duplicate “${dialog.spec.name}” to a draft`}
          confirmLabel={overwrite ? "Overwrite and duplicate" : "Duplicate"}
          danger={overwrite}
          busy={busy}
          confirmDisabled={!!problem}
          onCancel={close}
          onConfirm={() => void doDuplicate(dialog.spec.name, dialog.spec.source)}
        >
          <NameField name={name} setName={(n) => { setName(n); setOverwrite(false); setErr(null); }} problem={name ? problem : null} />
          <p className="muted">The file is copied as it is, comments included.</p>
          {err && <div className="fld-issues fld-error" role="alert">{err}{overwrite && " Confirm to replace it."}</div>}
        </ConfirmDialog>
      )}
      {dialog?.kind === "from-example" && (
        <ConfirmDialog
          title="New draft from an example"
          confirmLabel={overwrite ? "Overwrite and create" : "Create draft"}
          danger={overwrite}
          busy={busy}
          confirmDisabled={!!problem || !exampleName}
          onCancel={close}
          onConfirm={() => void doDuplicate(exampleName, "example")}
        >
          <label className="dlg-field">
            <span>Example</span>
            <select
              className="field"
              value={exampleName}
              onChange={(e) => {
                setExampleName(e.target.value);
                setName(`${e.target.value}-copy`);
                setOverwrite(false);
                setErr(null);
              }}
            >
              {allExamples.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <NameField name={name} setName={(n) => { setName(n); setOverwrite(false); setErr(null); }} problem={name ? problem : null} />
          {err && <div className="fld-issues fld-error" role="alert">{err}{overwrite && " Confirm to replace it."}</div>}
        </ConfirmDialog>
      )}
      {dialog?.kind === "delete" && (
        <ConfirmDialog
          title={`Delete draft “${dialog.spec.name}”?`}
          confirmLabel="Delete draft"
          danger
          busy={busy}
          onCancel={close}
          onConfirm={() => void doDelete(dialog.spec)}
        >
          <p>
            <code>{dialog.spec.path}</code> is removed. Runs already started from it keep their own copy of the spec.
          </p>
          {err && <div className="fld-issues fld-error" role="alert">{err}</div>}
        </ConfirmDialog>
      )}
    </>
  );
}

function NameField({ name, setName, problem }: { name: string; setName: (n: string) => void; problem: string | null }) {
  return (
    <label className="dlg-field">
      <span>Draft name</span>
      <input className="field" value={name} onChange={(e) => setName(e.target.value)} spellCheck={false} aria-invalid={!!problem} />
      {problem && <span className="fld-issues fld-error">{problem}</span>}
    </label>
  );
}

function shortHash(h: string | null) {
  return h ? h.slice(0, 12) : "–";
}

function SpecTable({ rows, actions }: { rows: SpecListEntry[]; actions: (s: SpecListEntry) => React.ReactNode }) {
  return (
    <div className="table-wrap">
      <table className="table spec-table">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Valid</th>
            <th scope="col">Hash</th>
            <th scope="col">Runtime / model</th>
            <th scope="col">Modified</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={`${s.source}:${s.name}`}>
              <td>
                <Link className="run-link" to={`/specs/${encodeURIComponent(s.name)}?source=${s.source}`}>
                  {s.name}
                </Link>
                {s.experiment_id && <div className="muted small">{s.experiment_id}</div>}
                {!s.valid && s.errors.length > 0 && (
                  <ul className="spec-errs">
                    {s.errors.slice(0, 2).map((e, i) => (
                      <li key={i}>
                        <code>{e.path || "spec"}</code> {e.message}
                      </li>
                    ))}
                  </ul>
                )}
              </td>
              <td>{s.valid ? <Badge tone="ok">valid</Badge> : <Badge tone="bad">invalid</Badge>}</td>
              <td>
                <code title={s.spec_hash ?? "no hash: the spec is invalid"}>{shortHash(s.spec_hash)}</code>
              </td>
              <td>
                <span className="rt-cell">
                  {s.runtime ?? "–"}
                  {s.model && <span className="muted"> · {s.model}</span>}
                  {isRealSpend(s) && (
                    <Badge tone="warn" title="This spec runs the real Claude Code agent: launching it spends usage">
                      real spend
                    </Badge>
                  )}
                </span>
              </td>
              <td className="muted small">{formatDateTime(s.mtime)}</td>
              <td>
                <div className="row-actions">{actions(s)}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
