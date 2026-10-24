import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge, Dialog, type Tone } from "../../components";
import { formatTokens, formatUsd } from "../../lib/format";
import { BudgetMeter } from "./BudgetMeter";
import { fmtOffset } from "./cardModel";
import { FeedCard } from "./FeedCard";
import { buildRows, type FeedRow } from "./feedStore";
import { Icon } from "./icons";
import { liveApi, transcriptLink } from "./liveApi";
import type { ContextWindow, DisplayEvent, Incident, IncidentGroup, KillInfo, RuleDoc, SafetyData, SafetyStatus } from "./types";
import { useTabBadge } from "./useTabBadge";

// ---- data ---------------------------------------------------------------------------------------------

/**
 * Keeps the last /safety answer while refreshing (no flicker). Polls while `live`; `refreshKey` changes
 * (an incident event arrived on the stream) trigger an immediate refetch.
 */
export function useSafety(runId: string, live: boolean, refreshKey = 0, pollMs = 5000) {
  const [data, setData] = useState<SafetyData | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const runRef = useRef(runId);

  useEffect(() => {
    if (runRef.current !== runId) {
      runRef.current = runId;
      setData(null);
      setLoading(true);
    }
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const go = async () => {
      try {
        const d = await liveApi.safety(runId, ctl.signal);
        if (ctl.signal.aborted) return;
        setData(d);
        setError(null);
      } catch (e) {
        if (ctl.signal.aborted) return;
        setError(e instanceof Error ? e : new Error(String(e)));
      } finally {
        if (!ctl.signal.aborted) {
          setLoading(false);
          if (live) timer = setTimeout(go, pollMs);
        }
      }
    };
    // a refresh caused by a stream event is slightly delayed so a burst becomes one request
    timer = setTimeout(go, refreshKey > 0 ? 250 : 0);
    return () => {
      ctl.abort();
      if (timer) clearTimeout(timer);
    };
  }, [runId, live, refreshKey, pollMs, tick]);

  return { data, error, loading, reload: useCallback(() => setTick((t) => t + 1), []) };
}

// ---- evidence highlight -------------------------------------------------------------------------------

/**
 * Evidence with the API's [start, end) character ranges marked. Ranges count Unicode code points (Python),
 * so we slice by code point, not by UTF-16 unit. Output is React text nodes and <mark> elements only.
 */
export function HighlightedEvidence({ text, ranges }: { text: string; ranges?: [number, number][] }) {
  const cps = useMemo(() => Array.from(text), [text]);
  const merged = useMemo(() => {
    const rs = (ranges ?? [])
      .filter((r) => Array.isArray(r) && Number.isFinite(r[0]) && Number.isFinite(r[1]))
      .map(([a, b]) => [Math.max(0, Math.min(cps.length, a)), Math.max(0, Math.min(cps.length, b))] as [number, number])
      .filter(([a, b]) => b > a)
      .sort((x, y) => x[0] - y[0]);
    const out: [number, number][] = [];
    for (const r of rs) {
      const last = out[out.length - 1];
      if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
      else out.push([r[0], r[1]]);
    }
    return out;
  }, [ranges, cps]);
  if (merged.length === 0) return <>{text}</>;
  const parts: ReactNode[] = [];
  let i = 0;
  merged.forEach(([a, b], n) => {
    if (a > i) parts.push(cps.slice(i, a).join(""));
    parts.push(<mark key={n} className="ev-mark">{cps.slice(a, b).join("")}</mark>);
    i = b;
  });
  if (i < cps.length) parts.push(cps.slice(i).join(""));
  return <>{parts}</>;
}

// ---- status light -------------------------------------------------------------------------------------

const STATUS_TEXT: Record<SafetyStatus, string> = {
  clear: "Clear",
  warnings: "Warnings",
  violations: "Violations",
  killed: "Killed",
};
const STATUS_HELP: Record<SafetyStatus, string> = {
  clear: "No guardrail rule has fired.",
  warnings: "Only logged warnings so far. No rule violation.",
  violations: "A rule was violated. See the incidents below.",
  killed: "The kill switch froze the agent.",
};

export function StatusLight({ data }: { data: SafetyData }) {
  const s = data.status;
  const c = data.counts;
  const bits = [
    c.kills > 0 ? `${c.kills} kill${c.kills === 1 ? "" : "s"}` : null,
    c.violations > 0 ? `${c.violations} violation${c.violations === 1 ? "" : "s"}` : null,
    c.warnings > 0 ? `${c.warnings} warning${c.warnings === 1 ? "" : "s"}` : null,
  ].filter(Boolean);
  return (
    <div className={`sl sl-${s}`} data-status={s}>
      <span className="sl-lamp" aria-hidden="true">
        <Icon name={s === "killed" ? "stop" : s === "clear" ? "check" : "shield"} size={26} />
      </span>
      <div className="sl-text">
        <div className="sl-label" role="status" aria-label={`Safety status: ${STATUS_TEXT[s]}`}>
          {STATUS_TEXT[s]}
        </div>
        <div className="sl-sub">{bits.length ? bits.join(" · ") : STATUS_HELP[s]}</div>
      </div>
    </div>
  );
}

// ---- kill banner --------------------------------------------------------------------------------------

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "not recorded";
  return ms < 10 ? `${ms.toFixed(1)} ms` : `${Math.round(ms)} ms`;
}

export function KillBanner({ runId, kill }: { runId: string; kill: KillInfo }) {
  const b = kill.budget;
  const budgetKill = kill.reason === "budget";
  return (
    <section className="kb" role="alert" aria-label="Kill switch fired" data-testid="kill-banner">
      <div className="kb-head">
        <Icon name="stop" size={22} />
        <span className="kb-title">KILL SWITCH FIRED</span>
        <span className="kb-rule mono">{kill.rule_id}</span>
      </div>
      <div className="kb-body">
        <dl className="kb-facts">
          <div><dt>Reason</dt><dd>{budgetKill ? "Spend cap reached" : kill.reason === "policy" ? "Policy rule" : kill.reason}</dd></div>
          <div>
            <dt>Detect to freeze</dt>
            <dd>
              <strong>{fmtMs(kill.detect_to_freeze_ms)}</strong>
              {kill.target_ms != null && kill.detect_to_freeze_ms != null && (
                <span className="muted"> (target {fmtMs(kill.target_ms)}, {kill.within_target ? "within" : "MISSED"})</span>
              )}
            </dd>
          </div>
          <div><dt>When</dt><dd>{kill.t_s != null ? `run time ${fmtOffset(kill.t_s)}` : "before the run clock started"}{kill.ts ? ` · ${kill.ts}` : ""}</dd></div>
          {kill.run_state && <div><dt>Run ended as</dt><dd>{kill.run_state.toLowerCase().replace(/_/g, " ")}</dd></div>}
          {b && (
            <div>
              <dt>Budget at kill</dt>
              <dd>
                {b.cost_usd != null ? formatUsd(b.cost_usd) : "–"}
                {b.per_run_usd != null && <span className="muted"> of {formatUsd(b.per_run_usd)}</span>}
                {b.tokens != null && <> {"·"} {formatTokens(b.tokens)} tokens{b.per_run_tokens != null ? <span className="muted"> of {formatTokens(b.per_run_tokens)}</span> : null}</>}
              </dd>
            </div>
          )}
        </dl>
        {kill.explanation && <p className="kb-expl">{kill.explanation}</p>}
        {kill.evidence && (
          <pre className="ev" aria-label="Kill evidence">
            <HighlightedEvidence text={kill.evidence} ranges={kill.evidence_highlight} />
          </pre>
        )}
        {kill.cursor && (
          <Link className="kb-link" to={transcriptLink(runId, kill.cursor)}>
            <Icon name="link" size={14} /> Open in transcript
          </Link>
        )}
      </div>
    </section>
  );
}

// ---- incident card ------------------------------------------------------------------------------------

function ContextView({ runId, ctx, focus }: { runId: string; ctx: ContextWindow; focus: string }) {
  const [events, setEvents] = useState<DisplayEvent[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  useEffect(() => {
    const ctl = new AbortController();
    liveApi
      .feedRange(runId, ctx.from_ref, ctx.to_ref, ctl.signal)
      .then((p) => !ctl.signal.aborted && setEvents(p.events))
      .catch((e: unknown) => !ctl.signal.aborted && setErr(e instanceof Error ? e.message : String(e)));
    return () => ctl.abort();
  }, [runId, ctx.from_ref, ctx.to_ref]);
  const toggle = useCallback((k: string) => setOpen((s) => {
    const n = new Set(s);
    if (n.has(k)) n.delete(k);
    else n.add(k);
    return n;
  }), []);
  const rows: FeedRow[] = useMemo(() => (events ? buildRows(events, { hidden: new Set(), minSeverity: "all", search: "" }) : []), [events]);
  if (err) return <div className="fc-note fc-note-bad" role="alert">Could not load the surrounding events: {err}</div>;
  if (!events) return <div className="muted fc-note">Loading the surrounding events…</div>;
  return (
    <div className="ctx">
      <div className="ctx-note muted">
        {ctx.exact ? `${ctx.before} events before and ${ctx.after} after the triggering call.` : "Approximate: the events nearest in time (this rule has no exact tool call)."}
      </div>
      <ol className="ctx-list" aria-label="Events around the incident">
        {rows.map((r) => {
          const center = r.ev.cursor === focus || r.result?.cursor === focus;
          return (
            <li key={r.key} className={center ? "ctx-center" : undefined} aria-current={center ? "true" : undefined}>
              {center && <span className="ctx-flag">trigger</span>}
              <FeedCard runId={runId} row={r} expanded={open.has(r.key)} onToggle={toggle} query="" />
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function IncidentCard({ runId, inc }: { runId: string; inc: Incident }) {
  const [showCtx, setShowCtx] = useState(false);
  const sevTone: Tone = inc.severity === "violation" ? "bad" : "warn";
  const killed = inc.killed || inc.action === "kill";
  return (
    <article className={`ic ic-${inc.severity}${killed ? " ic-kill" : ""}`} data-testid="incident" aria-label={`${inc.severity} ${inc.rule_id}`}>
      <header className="ic-head">
        <Badge tone={sevTone}>{inc.severity}</Badge>
        <span className="ic-rule mono">{inc.rule_id}</span>
        <Badge tone={killed ? "bad" : "neutral"} plain>{killed ? "action: kill" : `action: ${inc.action}`}</Badge>
        <Badge tone="neutral" plain title="Where the rule looked">{inc.channel}</Badge>
        <span className="ic-time muted" title={inc.ts ?? undefined}>
          {inc.t_s != null ? `t+${fmtOffset(inc.t_s)}` : "before start"}
        </span>
      </header>
      {inc.title && <div className="ic-title">{inc.title}</div>}
      {inc.evidence ? (
        <pre className="ev" aria-label="Evidence">
          <HighlightedEvidence text={inc.evidence} ranges={inc.evidence_highlight} />
          {inc.evidence_truncated ? " …" : ""}
        </pre>
      ) : (
        <div className="muted ic-noev">No evidence text was recorded.</div>
      )}
      {inc.explanation && <p className="ic-expl">{inc.explanation}</p>}
      {inc.why_it_matters && <p className="ic-why muted">{inc.why_it_matters}</p>}
      <div className="ic-actions">
        <button
          type="button"
          className="btn btn-small"
          aria-expanded={showCtx}
          disabled={!inc.context}
          title={inc.context ? undefined : "The agent stream does not reach this point"}
          onClick={() => setShowCtx((v) => !v)}
        >
          <Icon name="chevron" size={14} /> {showCtx ? "Hide context" : "Show context"}
        </button>
        <Link className="btn btn-small" to={transcriptLink(runId, inc.context?.center_ref ?? inc.cursor)}>
          <Icon name="link" size={14} /> Transcript
        </Link>
      </div>
      {showCtx && inc.context && <ContextView runId={runId} ctx={inc.context} focus={inc.context.center_ref} />}
    </article>
  );
}

// ---- groups / list ------------------------------------------------------------------------------------

const GROUP_PAGE = 20;

function GroupBlock({ runId, g, incidents }: { runId: string; g: IncidentGroup; incidents: Incident[] }) {
  const strong = g.killed || g.severity === "violation";
  const [open, setOpen] = useState(strong);
  const [limit, setLimit] = useState(GROUP_PAGE);
  const own = incidents.filter((i) => i.rule_id === g.rule_id);
  const tone: Tone = g.killed || g.severity === "violation" ? "bad" : "warn";
  return (
    <section className={`gr gr-${g.killed ? "kill" : g.severity}`}>
      <h3 className="gr-head">
        <button type="button" className="gr-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          <span className="gr-chev" aria-hidden="true"><Icon name="chevron" size={14} /></span>
          <span className="gr-rule mono">{g.rule_id}</span>
          <span className="gr-title">{g.title}</span>
          <span className="gr-meta">
            <Badge tone={tone}>{g.count}{"×"} {g.killed ? "kill" : g.severity}</Badge>
            {g.channels.map((c) => <Badge key={c} plain>{c}</Badge>)}
          </span>
        </button>
      </h3>
      {open && (
        <div className="gr-body">
          {g.explanation && <p className="gr-expl">{g.explanation}</p>}
          <div className="gr-span muted">
            {g.first_t_s != null && g.last_t_s != null ? `from ${fmtOffset(g.first_t_s)} to ${fmtOffset(g.last_t_s)} into the run` : null}
          </div>
          {own.slice(0, limit).map((i) => <IncidentCard key={i.id} runId={runId} inc={i} />)}
          {own.length > limit && (
            <button type="button" className="btn btn-small" onClick={() => setLimit((n) => n + GROUP_PAGE)}>Show {Math.min(GROUP_PAGE, own.length - limit)} more</button>
          )}
          {own.length < g.count && <div className="muted fc-note">{g.count - own.length} older incident{g.count - own.length === 1 ? "" : "s"} of this rule are not loaded here.</div>}
        </div>
      )}
    </section>
  );
}

function IncidentList({ runId, data }: { runId: string; data: SafetyData }) {
  const [mode, setMode] = useState<"rule" | "time">("rule");
  const [onlyViol, setOnlyViol] = useState(false);
  const [limit, setLimit] = useState(15);
  const flat = useMemo(() => data.incidents.filter((i) => !onlyViol || i.severity === "violation" || i.killed), [data.incidents, onlyViol]);
  if (data.incidents_total === 0 && data.groups.length === 0) {
    return <p className="muted sp-empty">No guardrail rule has fired in this run.</p>;
  }
  return (
    <div className="il">
      <div className="il-bar">
        <div className="seg" role="group" aria-label="Group incidents">
          <button type="button" className={`seg-b${mode === "rule" ? " on" : ""}`} aria-pressed={mode === "rule"} onClick={() => setMode("rule")}>By rule</button>
          <button type="button" className={`seg-b${mode === "time" ? " on" : ""}`} aria-pressed={mode === "time"} onClick={() => setMode("time")}>Newest first</button>
        </div>
        {mode === "time" && (
          <label className="il-only">
            <input type="checkbox" checked={onlyViol} onChange={(e) => setOnlyViol(e.target.checked)} /> Violations only
          </label>
        )}
      </div>
      {mode === "rule" ? (
        <div className="gr-list">{data.groups.map((g) => <GroupBlock key={g.rule_id} runId={runId} g={g} incidents={data.incidents} />)}</div>
      ) : (
        <div className="ic-list">
          {flat.slice(0, limit).map((i) => <IncidentCard key={i.id} runId={runId} inc={i} />)}
          {flat.length > limit && <button type="button" className="btn btn-small" onClick={() => setLimit((n) => n + 15)}>Show more</button>}
          {flat.length === 0 && <p className="muted sp-empty">No violations. Switch the filter off to see warnings.</p>}
        </div>
      )}
      {data.incidents_truncated && <p className="muted fc-note">Showing the newest {data.incidents.length} of {data.incidents_total} incidents. Counts above cover all of them.</p>}
    </div>
  );
}

// ---- noise, scorer signals, legend --------------------------------------------------------------------

function NoiseSummary({ data }: { data: SafetyData }) {
  if (!data.noise?.length) return null;
  return (
    <div className="noise">
      {data.noise.map((n) => (
        <details key={n.id} className="noise-item">
          <summary>
            <Icon name="fold" size={14} /> {n.title}
            <span className="muted"> {"–"} folded, not counted as incidents{n.open ? " (silent now)" : ""}</span>
          </summary>
          <p className="muted">{n.explanation}</p>
        </details>
      ))}
    </div>
  );
}

function ScorerSignals({ runId, data }: { runId: string; data: SafetyData }) {
  const s = data.scorer_signals;
  if (!s || (s.behavior_total === 0 && s.hazards_total === 0)) return null;
  const byDet = new Map<string, number>();
  for (const b of s.behavior) byDet.set(`${b.mode}/${b.detector}`, (byDet.get(`${b.mode}/${b.detector}`) ?? 0) + 1);
  return (
    <details className="scs">
      <summary>
        <Icon name="bars" size={14} /> Scorer signals
        <span className="muted"> {"–"} {s.hazards_total} hazard{s.hazards_total === 1 ? "" : "s"}, {s.behavior_total} behaviour signal{s.behavior_total === 1 ? "" : "s"}</span>
      </summary>
      {s.note && <p className="muted scs-note">{s.note}</p>}
      {s.hazards.length > 0 && (
        <ul className="scs-list" aria-label="Scorer hazards">
          {s.hazards.map((h) => (
            <li key={h.cursor}>
              <Badge tone="bad" plain>hazard</Badge> <span className="mono">{h.dimension}/{h.rule}</span> <span className="muted">checkpoint {h.k}</span>
              {h.evidence && <div className="scs-ev">{h.evidence}</div>}
              <Link className="scs-link" to={transcriptLink(runId, h.cursor)}>open</Link>
            </li>
          ))}
        </ul>
      )}
      {s.behavior.length > 0 && (
        <ul className="scs-list" aria-label="Scorer behaviour signals">
          {s.behavior.map((b) => (
            <li key={b.cursor}>
              <Badge tone={b.hazard ? "bad" : "neutral"} plain>{b.hazard ? "hazard" : "signal"}</Badge> <span className="mono">{b.mode}/{b.detector}</span> <span className="muted">checkpoint {b.k}</span>
              {b.evidence && <div className="scs-ev">{b.evidence}</div>}
            </li>
          ))}
          {s.behavior_total > s.behavior.length && <li className="muted">{s.behavior_total - s.behavior.length} more not listed here.</li>}
        </ul>
      )}
    </details>
  );
}

export function RuleLegend({ onClose }: { onClose: () => void }) {
  const [rules, setRules] = useState<RuleDoc[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    liveApi
      .rules(ctl.signal)
      .then((r) => !ctl.signal.aborted && setRules(r.rules))
      .catch((e: unknown) => !ctl.signal.aborted && setErr(e instanceof Error ? e.message : String(e)));
    return () => ctl.abort();
  }, []);
  return (
    <Dialog title="Guardrail rules" onClose={onClose}>
      <p className="muted">What each rule protects, taken from the policy file the run used. Observation only: the panel never changes a rule.</p>
      {err && <div role="alert" className="fc-note fc-note-bad">Could not load the rules: {err}</div>}
      {!rules && !err && <div className="muted">Loading…</div>}
      <dl className="legend">
        {rules?.map((r) => (
          <div key={r.rule_id} className="legend-item">
            <dt>
              <span className="mono">{r.rule_id}</span> <span className="legend-title">{r.title}</span>{" "}
              {r.policy?.action && <Badge plain tone={r.policy.action === "kill" ? "bad" : "neutral"}>{r.policy.action}</Badge>}{" "}
              <Badge plain>{r.category}</Badge>
            </dt>
            <dd>{r.protects}</dd>
            <dd className="muted">{r.why}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}

// ---- the panel ----------------------------------------------------------------------------------------

/** Presentational: everything from one /safety answer. */
export function SafetyPanelView({ runId, data, live }: { runId: string; data: SafetyData; live: boolean }) {
  const [legend, setLegend] = useState(false);
  const meter = data.budget?.meter;
  return (
    <div className="sp" data-status={data.status}>
      <StatusLight data={data} />
      {data.kill && <KillBanner runId={runId} kill={data.kill} />}
      {meter && (
        <div className="sp-section">
          <h3 className="sp-h">Budget</h3>
          <BudgetMeter meter={meter} costUsd={meter.cost_usd} tokens={meter.tokens} />
        </div>
      )}
      <div className="sp-section">
        <div className="sp-h-row">
          <h3 className="sp-h">Incidents</h3>
          <button type="button" className="btn btn-small" onClick={() => setLegend(true)}>
            <Icon name="info" size={14} /> Rule legend
          </button>
        </div>
        <IncidentList runId={runId} data={data} />
        <NoiseSummary data={data} />
        {data.policy && data.policy.verified === false && (
          <p className="fc-note fc-note-warn">The policy file on disk differs from the one this run used; explanations may not match exactly.</p>
        )}
      </div>
      <ScorerSignals runId={runId} data={data} />
      {live && <p className="muted sp-foot">Observing only. This panel never blocks, probes or changes the agent.</p>}
      {legend && <RuleLegend onClose={() => setLegend(false)} />}
    </div>
  );
}

/**
 * The safety panel. Mount it with just a run id (live pages and, later, the run-detail page). It fetches
 * /api/runs/{id}/safety itself, polls while `live`, and refreshes immediately when `refreshKey` changes.
 */
export function SafetyPanel({
  runId,
  live = false,
  refreshKey = 0,
  pollMs,
  badge = true,
}: {
  runId: string;
  live?: boolean;
  refreshKey?: number;
  pollMs?: number;
  /** Put "(n!)" in the tab title when new violations arrive while the tab is hidden. */
  badge?: boolean;
}) {
  const { data, error, loading, reload } = useSafety(runId, live, refreshKey, pollMs);
  useTabBadge(badge && data ? data.counts.violations + data.counts.kills : null);
  if (!data) {
    return (
      <div className="sp sp-loading">
        {error ? (
          <div role="alert" className="fc-note fc-note-bad">
            Could not load the safety data: {error.message} <button type="button" className="btn btn-small" onClick={reload}>Try again</button>
          </div>
        ) : (
          <div className="muted" role="status">{loading ? "Loading safety data…" : ""}</div>
        )}
      </div>
    );
  }
  return (
    <>
      {error && <div className="fc-note fc-note-warn" role="status">Refresh failed ({error.message}); showing the last data.</div>}
      <SafetyPanelView runId={runId} data={data} live={live || data.live} />
    </>
  );
}
