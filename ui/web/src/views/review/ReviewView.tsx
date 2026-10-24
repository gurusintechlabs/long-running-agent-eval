import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  reviewApi,
  useAsync,
  type ReviewDecisionKind,
  type ReviewDecisionRecord,
  type ReviewItem,
  type ReviewQueueResponse,
} from "../../api";
import { Badge, Card, ConfirmDialog, EmptyState, ErrorState, Spinner } from "../../components";
import {
  DEFAULT_FILTERS,
  STATUS_FILTERS,
  applyDecisions,
  countItems,
  filterItems,
  formatClock,
  groupOptions,
  isTypingTarget,
  matchesStatus,
  nameOptions,
  transcriptHref,
  type ReviewFilters,
  type StatusFilter,
} from "./reviewLogic";
import "./review.css";

const DECISIONS: { value: ReviewDecisionKind; label: string; key: string; tone: "ok" | "bad" | "warn" }[] = [
  { value: "confirm", label: "Confirm", key: "c", tone: "ok" },
  { value: "reject", label: "Reject", key: "r", tone: "bad" },
  { value: "unsure", label: "Unsure", key: "u", tone: "warn" },
];

export function ReviewView() {
  const { runId } = useParams();
  return runId ? <ReviewQueue runId={runId} /> : <ReviewRuns />;
}

// ---------- overview of runs ----------

function ReviewRuns() {
  const q = useAsync((s) => reviewApi.runs(s), []);
  useEffect(() => {
    document.title = "Review · LRAE";
  }, []);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Review</h1>
          <div className="page-sub">Label the hazards and behaviour findings the scorer flagged. Decisions are appended to each run's review log.</div>
        </div>
      </div>
      {q.loading && <Spinner label="Loading review runs" />}
      {q.error && <ErrorState title="Cannot load the review queue" error={q.error} onRetry={q.reload} />}
      {q.data && q.data.runs.length === 0 && (
        <EmptyState title="Nothing to review">No run has a scorer log with hazard or behaviour findings yet.</EmptyState>
      )}
      {q.data && q.data.runs.length > 0 && (
        <Card flush>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col" className="num">Items</th>
                  <th scope="col" className="num">Pending</th>
                  <th scope="col" className="num">Confirmed</th>
                  <th scope="col" className="num">Rejected</th>
                  <th scope="col" className="num">Unsure</th>
                  <th scope="col">Progress</th>
                </tr>
              </thead>
              <tbody>
                {q.data.runs.map((r) => (
                  <tr key={r.run_id}>
                    <td>
                      <Link className="run-link" to={`/review/${encodeURIComponent(r.run_id)}`}>
                        {r.run_id}
                      </Link>
                    </td>
                    <td className="num">{r.items}</td>
                    <td className="num">{r.pending}</td>
                    <td className="num">{r.confirm}</td>
                    <td className="num">{r.reject}</td>
                    <td className="num">{r.unsure}</td>
                    <td>
                      <Progress done={r.items - r.pending} total={r.items} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

function Progress({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="rv-progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done} aria-label={`${done} of ${total} decided`}>
      <div className="rv-progress-bar" style={{ width: `${pct}%` }} />
      <span className="rv-progress-text">
        {done}/{total} ({pct}%)
      </span>
    </div>
  );
}

// ---------- one run's queue ----------

function ReviewQueue({ runId }: { runId: string }) {
  const q = useAsync((s) => reviewApi.queueAll(runId, s), [runId]);
  useEffect(() => {
    document.title = `Review ${runId} · LRAE`;
  }, [runId]);
  if (q.error) return <ErrorState title="Cannot load this run's review queue" error={q.error} onRetry={q.reload} />;
  if (!q.data) return <Spinner label="Loading review items" />;
  return <Board key={runId} runId={runId} initial={q.data} />;
}

function Board({ runId, initial }: { runId: string; initial: ReviewQueueResponse }) {
  const [items, setItems] = useState<ReviewItem[]>(initial.items);
  const [params, setParams] = useSearchParams();
  const filters: ReviewFilters = {
    status: (STATUS_FILTERS.some((s) => s.value === params.get("status")) ? params.get("status") : DEFAULT_FILTERS.status) as StatusFilter,
    kind: params.get("kind") ?? "",
    group: params.get("group") ?? "",
    name: params.get("name") ?? "",
  };
  const setFilters = (patch: Partial<ReviewFilters>) => {
    const next = { ...filters, ...patch };
    if (patch.group !== undefined && patch.group !== filters.group && patch.name === undefined) next.name = "";
    const p = new URLSearchParams();
    if (next.status !== DEFAULT_FILTERS.status) p.set("status", next.status);
    for (const k of ["kind", "group", "name"] as const) if (next[k]) p.set(k, next[k]);
    setParams(p, { replace: true });
    setSel(0);
  };

  const [sel, setSel] = useState(0);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [batch, setBatch] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const noteRefs = useRef(new Map<string, HTMLTextAreaElement>());

  const shown = useMemo(() => filterItems(items, filters), [items, filters.status, filters.kind, filters.group, filters.name]); // eslint-disable-line react-hooks/exhaustive-deps
  const counts = useMemo(() => countItems(items), [items]);
  const groups = useMemo(() => groupOptions(items), [items]);
  const names = useMemo(() => nameOptions(items, filters.group), [items, filters.group]);
  const kinds = useMemo(() => [...new Set(items.map((i) => i.kind))].sort(), [items]);
  const cur = Math.min(sel, Math.max(0, shown.length - 1));
  const current = shown[cur];
  const narrowed = !!(filters.group || filters.name || filters.kind);

  useEffect(() => {
    if (!current) return;
    document.getElementById(`item-${current.item_id}`)?.scrollIntoView?.({ block: "nearest" });
  }, [current?.item_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const decide = useCallback(
    async (item: ReviewItem, decision: ReviewDecisionKind) => {
      if (busy) return;
      setBusy(true);
      setError(null);
      try {
        const note = (notes[item.item_id] ?? "").trim();
        const r = await reviewApi.decide(runId, item.item_id, decision, note || null);
        setItems((prev) => applyDecisions(prev, [r.decision]));
        setNotes((n) => {
          const { [item.item_id]: _drop, ...rest } = n;
          void _drop;
          return rest;
        });
        // the item stays in view unless the status filter now hides it; either way the cursor moves on
        if (matchesStatus({ status: decision }, filters.status)) setSel(cur + 1);
      } catch (e) {
        setError(e instanceof Error ? e.message : "could not record the decision");
      } finally {
        setBusy(false);
      }
    },
    [busy, notes, runId, filters.status, cur],
  );

  // keyboard flow
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || batch) return;
      if (e.key === "Escape" && isTypingTarget(e.target)) {
        (e.target as HTMLElement).blur();
        return;
      }
      if (isTypingTarget(e.target)) return;
      if (e.key === "j") setSel(Math.min(cur + 1, shown.length - 1));
      else if (e.key === "k") setSel(Math.max(cur - 1, 0));
      else if (e.key === "n" && current) {
        e.preventDefault();
        noteRefs.current.get(current.item_id)?.focus();
      } else if (current) {
        const d = DECISIONS.find((x) => x.key === e.key);
        if (d) {
          e.preventDefault();
          void decide(current, d.value);
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [cur, shown.length, current, decide, batch]);

  const decided = items.length - counts.pending;

  const doBatch = async (decision: ReviewDecisionKind, note: string) => {
    setBusy(true);
    setError(null);
    try {
      const targets = shown;
      const recs: ReviewDecisionRecord[] = [];
      for (let i = 0; i < targets.length; i += 500) {
        const r = await reviewApi.decideBatch(
          runId,
          targets.slice(i, i + 500).map((t) => ({ item_id: t.item_id, decision, ...(note ? { note } : {}) })),
        );
        recs.push(...r.decisions);
      }
      setItems((prev) => applyDecisions(prev, recs));
      setFlash(`Recorded ${recs.length} “${decision}” decision${recs.length === 1 ? "" : "s"}.`);
      setBatch(false);
      setSel(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "batch failed");
      setBatch(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rv">
      <div className="crumbs">
        <Link to="/review">← Review</Link>
      </div>
      <div className="page-head">
        <div>
          <h1 className="rv-title">{runId}</h1>
          <div className="page-sub">
            {items.length} item{items.length === 1 ? "" : "s"} · {shown.length} shown
            {initial.total > items.length && ` · only the first ${items.length} of ${initial.total} loaded`}
          </div>
        </div>
        <Link className="btn" to={`/runs/${encodeURIComponent(runId)}`}>
          Run details
        </Link>
      </div>

      <div className="rv-counters" aria-label="Progress">
        <Progress done={decided} total={items.length} />
        <span className="rv-chips">
          <Badge tone="neutral">{counts.pending} pending</Badge>
          <Badge tone="ok">{counts.confirm} confirmed</Badge>
          <Badge tone="bad">{counts.reject} rejected</Badge>
          <Badge tone="warn">{counts.unsure} unsure</Badge>
        </span>
      </div>

      <form className="toolbar rv-toolbar" role="search" aria-label="Filter review items" onSubmit={(e) => e.preventDefault()}>
        <label className="tb-field">
          <span className="tb-label">Status</span>
          <select className="field" value={filters.status} onChange={(e) => setFilters({ status: e.target.value as StatusFilter })}>
            {STATUS_FILTERS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="tb-field">
          <span className="tb-label">Kind</span>
          <select className="field" value={filters.kind} onChange={(e) => setFilters({ kind: e.target.value })}>
            <option value="">Any</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label className="tb-field">
          <span className="tb-label">Group</span>
          <select className="field" value={filters.group} onChange={(e) => setFilters({ group: e.target.value })}>
            <option value="">Any</option>
            {groups.map((g) => (
              <option key={g.value} value={g.value}>
                {g.value} ({g.count})
              </option>
            ))}
          </select>
        </label>
        <label className="tb-field">
          <span className="tb-label">Detector</span>
          <select className="field" value={filters.name} onChange={(e) => setFilters({ name: e.target.value })}>
            <option value="">Any</option>
            {names.map((g) => (
              <option key={g.value} value={g.value}>
                {g.value} ({g.count})
              </option>
            ))}
          </select>
        </label>
        <div className="tb-field rv-batch">
          <button
            type="button"
            className="btn"
            disabled={!narrowed || shown.length === 0 || busy}
            title={narrowed ? "Give the same decision to every item shown" : "Pick a group, detector or kind first"}
            onClick={() => setBatch(true)}
          >
            Decide all {narrowed ? shown.length : ""} shown…
          </button>
        </div>
      </form>

      {error && (
        <div className="banner banner-bad" role="alert">
          {error}
        </div>
      )}
      {flash && (
        <div className="banner banner-ok" role="status">
          {flash}
        </div>
      )}

      {shown.length === 0 ? (
        <EmptyState title={items.length === 0 ? "No findings in this run" : filters.status === "pending" && counts.pending === 0 ? "All done" : "Nothing matches these filters"}>
          {filters.status === "pending" && counts.pending === 0 && items.length > 0
            ? "Every item has a decision. Switch Status to All to review them."
            : "Change the filters to see more items."}
        </EmptyState>
      ) : (
        <ol className="rv-list" aria-label="Review items">
          {shown.map((it, idx) => (
            <ItemCard
              key={it.item_id}
              item={it}
              selected={idx === cur}
              note={notes[it.item_id] ?? ""}
              setNote={(v) => setNotes((n) => ({ ...n, [it.item_id]: v }))}
              noteRef={(el) => {
                if (el) noteRefs.current.set(it.item_id, el);
                else noteRefs.current.delete(it.item_id);
              }}
              onSelect={() => setSel(idx)}
              onDecide={(d) => void decide(it, d)}
              busy={busy}
            />
          ))}
        </ol>
      )}

      <p className="rv-keys muted">
        Keys: <kbd>j</kbd>/<kbd>k</kbd> next/previous · <kbd>c</kbd> confirm · <kbd>r</kbd> reject · <kbd>u</kbd> unsure · <kbd>n</kbd> note (<kbd>Esc</kbd> to leave it)
      </p>

      {batch && (
        <BatchDialog
          count={shown.length}
          alreadyDecided={shown.filter((s) => s.status !== "pending").length}
          describe={[filters.kind && `kind ${filters.kind}`, filters.group && `group ${filters.group}`, filters.name && `detector ${filters.name}`].filter(Boolean).join(", ")}
          busy={busy}
          onCancel={() => setBatch(false)}
          onConfirm={(d, n) => void doBatch(d, n)}
        />
      )}
    </div>
  );
}

function BatchDialog({
  count,
  alreadyDecided,
  describe,
  busy,
  onCancel,
  onConfirm,
}: {
  count: number;
  alreadyDecided: number;
  describe: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (d: ReviewDecisionKind, note: string) => void;
}) {
  const [decision, setDecision] = useState<ReviewDecisionKind>("confirm");
  const [note, setNote] = useState("");
  return (
    <ConfirmDialog
      title={`Decide ${count} item${count === 1 ? "" : "s"} at once`}
      confirmLabel={`Record ${count} “${decision}” decision${count === 1 ? "" : "s"}`}
      busy={busy}
      onCancel={onCancel}
      onConfirm={() => onConfirm(decision, note.trim())}
    >
      <p>
        Every item shown ({describe || "current filters"}) gets the same decision. Nothing is overwritten: each decision is appended to the review log and the earlier ones stay in the item's history.
        {alreadyDecided > 0 && ` ${alreadyDecided} of them already have a decision and will get a new one.`}
      </p>
      <fieldset className="rv-radios">
        <legend>Decision</legend>
        {DECISIONS.map((d) => (
          <label key={d.value}>
            <input type="radio" name="batch-decision" checked={decision === d.value} onChange={() => setDecision(d.value)} /> {d.label}
          </label>
        ))}
      </fieldset>
      <label className="dlg-field">
        <span>Note (optional, 2000 characters)</span>
        <textarea className="field" rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
    </ConfirmDialog>
  );
}

// ---------- item card ----------

function ItemCard({
  item,
  selected,
  note,
  setNote,
  noteRef,
  onSelect,
  onDecide,
  busy,
}: {
  item: ReviewItem;
  selected: boolean;
  note: string;
  setNote: (v: string) => void;
  noteRef: (el: HTMLTextAreaElement | null) => void;
  onSelect: () => void;
  onDecide: (d: ReviewDecisionKind) => void;
  busy: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const evidence = item.evidence ?? "";
  const long = evidence.length > 360 || evidence.split("\n").length > 6;
  const latest = item.decision;
  const tone = item.status === "confirm" ? "ok" : item.status === "reject" ? "bad" : item.status === "unsure" ? "warn" : "neutral";
  return (
    <li
      id={`item-${item.item_id}`}
      className={`rv-card${selected ? " rv-selected" : ""}`}
      aria-current={selected ? "true" : undefined}
      onClick={onSelect}
    >
      <header className="rv-card-head">
        <Badge tone={item.kind === "hazard" ? "bad" : "info"} plain>
          {item.kind}
        </Badge>
        <span className="rv-group">{item.group}</span>
        <strong className="rv-name">{item.name}</strong>
        <span className="rv-tag" title={item.deterministic === true ? "Deterministic rule" : item.deterministic === false ? "LLM judge" : "Not applicable"}>
          {item.deterministic === true ? "rule" : item.deterministic === false ? "judge" : "scorer"}
        </span>
        <span className="rv-spacer" />
        <span className="muted rv-time">
          {item.k != null && <>ck {item.k} · </>}
          {formatClock(item.context?.cursor?.t_s ?? item.t_s)}
        </span>
        <Link className="rv-link" to={transcriptHref(item)}>
          Transcript →
        </Link>
      </header>

      {item.title && item.title !== `${item.group} ${item.name}` && <div className="rv-title-line">{item.title}</div>}

      {evidence ? (
        <pre className={`rv-evidence${expanded || !long ? "" : " rv-clamped"}`}>{evidence}</pre>
      ) : (
        <div className="muted">No evidence text.</div>
      )}
      {long && (
        <button type="button" className="link-btn rv-more" onClick={() => setExpanded(!expanded)}>
          {expanded ? "Show less" : "Show all evidence"}
        </button>
      )}

      {item.proposed_label && (
        <div className="rv-draft">
          <Badge tone="info" plain>
            draft label: {item.proposed_label}
          </Badge>
          {item.draft_note && <span className="muted">{item.draft_note}</span>}
        </div>
      )}

      <div className="rv-decide">
        <div className="rv-btns" role="group" aria-label="Decision">
          {DECISIONS.map((d) => (
            <button
              key={d.value}
              type="button"
              className={`btn rv-dbtn rv-${d.tone}${item.status === d.value ? " rv-on" : ""}`}
              disabled={busy}
              aria-pressed={item.status === d.value}
              onClick={(e) => {
                e.stopPropagation();
                onDecide(d.value);
              }}
            >
              {d.label} <kbd>{d.key}</kbd>
            </button>
          ))}
        </div>
        <textarea
          ref={noteRef}
          className="field rv-note"
          rows={1}
          maxLength={2000}
          placeholder="Note (optional, key n)"
          aria-label={`Note for ${item.group} ${item.name}`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onClick={(e) => e.stopPropagation()}
        />
      </div>

      <footer className="rv-foot">
        <span className="rv-latest">
          {latest ? (
            <>
              <Badge tone={tone}>{item.status}</Badge>{" "}
              <span className="muted">
                {latest.reviewer ? `by ${latest.reviewer} · ` : ""}
                {latest.ts}
              </span>
              {latest.note && <span className="rv-latest-note"> “{latest.note}”</span>}
            </>
          ) : (
            <Badge tone="neutral">pending</Badge>
          )}
        </span>
        {item.history_count > 0 && (
          <button type="button" className="link-btn" aria-expanded={showHistory} onClick={() => setShowHistory(!showHistory)}>
            History ({item.history_count})
          </button>
        )}
      </footer>
      {showHistory && <History runId={item.run_id} itemId={item.item_id} count={item.history_count} />}
    </li>
  );
}

function History({ runId, itemId, count }: { runId: string; itemId: string; count: number }) {
  const q = useAsync((s) => reviewApi.history(runId, itemId, s), [runId, itemId, count]);
  if (q.error) return <div className="fld-issues fld-error">Cannot load history: {q.error.message}</div>;
  if (!q.data) return <div className="muted">Loading history…</div>;
  const rows = [...q.data.history].reverse();
  return (
    <ol className="rv-history" aria-label="Decision history, newest first">
      {rows.map((r, i) => (
        <li key={`${r.ts}-${i}`}>
          <Badge tone={r.decision === "confirm" ? "ok" : r.decision === "reject" ? "bad" : "warn"}>{r.decision}</Badge>
          <span className="muted">
            {" "}
            {r.ts}
            {r.reviewer ? ` · ${r.reviewer}` : ""}
          </span>
          {r.note && <span> “{r.note}”</span>}
          {i === 0 && <span className="muted"> (latest)</span>}
        </li>
      ))}
    </ol>
  );
}
