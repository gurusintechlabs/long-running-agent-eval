import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  judgesApi,
  useAsync,
  type ClaimStage,
  type JudgeCheckpoint,
  type JudgeFinding,
  type JudgesResponse,
} from "../../../api";
import { Badge, Card, EmptyState, ErrorState, Spinner } from "../../../components";
import { EMPTY, formatDuration, formatNumber, formatUsd } from "../../../lib/format";
import { transcriptLink } from "../common/links";
import { Chip } from "../common/Widgets";
import "./judges.css";

/** Every LLM judgement of the run, per checkpoint. Read only: nothing is re-judged here. */
export function JudgesTab({ runId, live }: { runId: string; live: boolean }) {
  const q = useAsync((s) => judgesApi.get(runId, s), [runId], () => (live ? 15000 : null));
  if (q.error && !q.data) return <Card><ErrorState title="Could not load the judges' results" error={q.error} onRetry={q.reload} /></Card>;
  if (!q.data) return <Spinner label="Loading judgements" />;
  if (!q.data.ingested) {
    return (
      <Card>
        <EmptyState title="No judgements yet">{q.data.reason}</EmptyState>
      </Card>
    );
  }
  return <JudgesBody runId={runId} d={q.data} />;
}

function hasNotes(c: JudgeCheckpoint): boolean {
  const s = c.summary;
  return (s.x ?? 0) > 0 || s.drift > 0 || s.misstatements > 0 || s.tactics > 0 || s.findings > 0;
}

function JudgesBody({ runId, d }: { runId: string; d: JudgesResponse }) {
  const [params] = useSearchParams();
  const kParam = params.get("k");
  const focus = kParam != null && /^\d{1,6}$/.test(kParam) ? Number(kParam) : null;
  const [onlyNotes, setOnlyNotes] = useState(false);
  const judged = d.checkpoints.filter((c) => c.quality || c.goals || c.claims || c.manipulation);
  const shown = onlyNotes ? judged.filter((c) => hasNotes(c) || c.k === focus) : judged;
  const total = useMemo(() => judged.reduce((a, c) => a + (c.cost_usd ?? 0), 0), [judged]);

  useEffect(() => {
    if (focus == null) return;
    document.getElementById(`judge-k${focus}`)?.scrollIntoView?.({ block: "start" });
  }, [focus, shown.length]);

  if (judged.length === 0) {
    return (
      <Card>
        <EmptyState title="No judge ran for this run">The spec's scoring has no LLM judges, or no checkpoint has been scored yet.</EmptyState>
      </Card>
    );
  }
  return (
    <>
      <Card
        title="Judges"
        actions={
          <Chip on={onlyNotes} onClick={() => setOnlyNotes(!onlyNotes)} title="Hide checkpoints where no judge found anything">
            Only checkpoints with findings
          </Chip>
        }
      >
        <p className="muted jd-intro">
          What each LLM judge concluded at each checkpoint{d.judge_model ? <> (model <span className="mono">{d.judge_model}</span>)</> : null}:
          the quality judge's contradictions (X), the goal observer's inferred goals and drift, the prose-claims audit and the manipulation check.
          {" "}Judge spend over {judged.length} checkpoint{judged.length === 1 ? "" : "s"}: {formatUsd(total)}.
        </p>
      </Card>
      {shown.length === 0 && (
        <Card>
          <EmptyState title="No judge found anything">Every judged checkpoint is clean. Turn off the filter to see the judges' full output.</EmptyState>
        </Card>
      )}
      {shown.map((c) => (
        <CheckpointJudgements key={c.k} runId={runId} c={c} focused={c.k === focus} />
      ))}
    </>
  );
}

function SummaryChips({ c }: { c: JudgeCheckpoint }) {
  const s = c.summary;
  return (
    <span className="jd-chips">
      {s.x != null && <Badge tone={s.x > 0 ? "warn" : "ok"} plain title="Quality judge: contradictions found (X)">X {formatNumber(s.x, 1)}</Badge>}
      {s.fidelity != null && <Badge tone="info" plain title="Goal observer: fidelity to the brief">fidelity {formatNumber(s.fidelity, 2)}</Badge>}
      {s.drift > 0 && <Badge tone="warn" plain title="Goal observer: drift items">{s.drift} drift</Badge>}
      {s.misstatements > 0 && <Badge tone="bad" plain title="Prose-claims audit: misstatements">{s.misstatements} misstated</Badge>}
      {s.tactics > 0 && <Badge tone="bad" plain title="Manipulation check: tactics">{s.tactics} tactic{s.tactics === 1 ? "" : "s"}</Badge>}
    </span>
  );
}

function CheckpointJudgements({ runId, c, focused }: { runId: string; c: JudgeCheckpoint; focused: boolean }) {
  const open = focused || hasNotes(c);
  return (
    <section id={`judge-k${c.k}`} className={`card jd-cp${focused ? " jd-focus" : ""}`}>
      <details open={open}>
        <summary className="jd-sum">
          <strong>t{c.k}</strong>
          <span className="muted">{formatDuration(c.t_s)}</span>
          <SummaryChips c={c} />
          <span className="muted jd-cost">{c.cost_usd != null ? formatUsd(c.cost_usd) : EMPTY}</span>
        </summary>
        <div className="jd-body">
          <QualitySection c={c} />
          <GoalsSection c={c} />
          <ClaimsSection stages={c.claims?.stages ?? null} reason={c.claims?.reason ?? null} present={c.claims != null} />
          <ManipulationSection c={c} />
          <FindingsSection runId={runId} findings={c.findings} />
        </div>
      </details>
    </section>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="jd-sec">
      <h3>
        {title}
        {hint && <span className="muted jd-hint"> {hint}</span>}
      </h3>
      {children}
    </div>
  );
}

const Quote = ({ label, text }: { label: string; text?: string | null }) =>
  text ? (
    <div className="jd-q">
      <span className="jd-ql">{label}</span>
      <span className="jd-qt">{text}</span>
    </div>
  ) : null;

function QualitySection({ c }: { c: JudgeCheckpoint }) {
  const q = c.quality;
  if (!q) return null;
  const n = q.samples.length;
  return (
    <Section title="Quality judge (X)" hint={`X = ${formatNumber(q.value, 1)}${q.spread != null ? `, spread ${formatNumber(q.spread, 2)}` : ""}${n ? `, ${n} sample${n === 1 ? "" : "s"}` : ""}`}>
      {q.reason && <p className="muted">{q.reason}</p>}
      {q.samples.map((s) => (
        <div key={s.index} className="jd-sample">
          {n > 1 && <div className="jd-sample-h muted">Sample {s.index + 1}: {s.count} contradiction{s.count === 1 ? "" : "s"}{s.cached ? " (cached)" : ""}</div>}
          {s.contradictions.length === 0 ? (
            <p className="muted">No contradictions between the agent's statements.</p>
          ) : (
            <ol className="jd-list">
              {s.contradictions.map((x, i) => (
                <li key={i}>
                  {x.kind && <Badge plain>{x.kind.replace(/_/g, " ")}</Badge>}
                  <Quote label="Earlier" text={x.earlier} />
                  <Quote label="Later" text={x.later} />
                  <Quote label="Why" text={x.evidence} />
                </li>
              ))}
            </ol>
          )}
        </div>
      ))}
    </Section>
  );
}

function GoalsSection({ c }: { c: JudgeCheckpoint }) {
  const g = c.goals;
  if (!g) return null;
  return (
    <Section title="Goal observer" hint={g.fidelity != null ? `fidelity ${formatNumber(g.fidelity, 2)}` : undefined}>
      {g.reason && <p className="muted">{g.reason}</p>}
      {g.drift.length > 0 ? (
        <ol className="jd-list">
          {g.drift.map((x, i) => (
            <li key={i}>
              <Quote label="Asked" text={x.instruction} />
              <Quote label="Did" text={x.instead} />
              <Quote label="Evidence" text={x.evidence} />
            </li>
          ))}
        </ol>
      ) : (
        !g.reason && <p className="muted">No drift from the brief or the rules.</p>
      )}
      {g.priority_inversions.length > 0 && (
        <>
          <h4>Priority inversions</h4>
          <ol className="jd-list">
            {g.priority_inversions.map((x, i) => (
              <li key={i}>{typeof x === "string" ? x : <pre className="jd-raw">{JSON.stringify(x, null, 2)}</pre>}</li>
            ))}
          </ol>
        </>
      )}
      {g.inferred_goals.length > 0 && (
        <details className="jd-goals">
          <summary>Inferred goals ({g.inferred_goals.length})</summary>
          <ol className="jd-list">
            {g.inferred_goals.map((x, i) => (
              <li key={i}>
                <div>{x.goal}</div>
                {x.evidence && <div className="muted jd-ev">{x.evidence}</div>}
              </li>
            ))}
          </ol>
        </details>
      )}
    </Section>
  );
}

function ClaimsSection({ stages, reason, present }: { stages: ClaimStage[] | null; reason: string | null; present: boolean }) {
  if (!present) return null;
  const items = (stages ?? []).flatMap((s) => s.misstatements.map((m) => ({ stage: s.stage, m })));
  const dropped = (stages ?? []).flatMap((s) => s.dropped.map((x) => ({ stage: s.stage, x })));
  const label = (stages ?? []).map((s) => s.stage).filter((s) => s != null);
  return (
    <Section title="Prose claims" hint={label.length ? `stage${label.length === 1 ? "" : "s"} ${label.join(", ")}` : undefined}>
      {reason && <p className="muted">{reason}</p>}
      {items.length === 0 && !reason && <p className="muted">The agent's summaries match what the scorer measured.</p>}
      {items.length > 0 && (
        <ol className="jd-list">
          {items.map(({ stage, m }, i) => (
            <li key={i}>
              <Badge tone={m.kind === "contradicted" ? "bad" : "warn"} plain>{m.kind ?? "misstatement"}</Badge>
              {stage != null && <span className="muted"> stage {stage}</span>}
              <Quote label="Claim" text={m.claim} />
              <Quote label="Fact" text={m.fact} />
              <Quote label="Why" text={m.evidence} />
            </li>
          ))}
        </ol>
      )}
      {dropped.length > 0 && (
        <details>
          <summary className="muted">Claims the judge could not check ({dropped.length})</summary>
          <ol className="jd-list">
            {dropped.map(({ x }, i) => (
              <li key={i}>{typeof x === "string" ? x : <pre className="jd-raw">{JSON.stringify(x, null, 2)}</pre>}</li>
            ))}
          </ol>
        </details>
      )}
    </Section>
  );
}

function ManipulationSection({ c }: { c: JudgeCheckpoint }) {
  const m = c.manipulation;
  if (!m) return null;
  return (
    <Section title="Manipulation check" hint="messages to the ops channel">
      {m.reason && <p className="muted">{m.reason}</p>}
      {m.tactics.length === 0 && !m.reason && <p className="muted">No manipulation tactics.</p>}
      {m.tactics.length > 0 && (
        <ol className="jd-list">
          {m.tactics.map((t, i) => (
            <li key={i}>
              <Badge tone="bad" plain>{t.tactic ?? "tactic"}</Badge>
              {t.request && <span className="muted"> in a {t.request}</span>}
              <Quote label="Quote" text={t.quote} />
              <Quote label="Why" text={t.evidence} />
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

function FindingsSection({ runId, findings }: { runId: string; findings: JudgeFinding[] }) {
  if (findings.length === 0) return null;
  return (
    <Section title="Recorded findings" hint="behaviour events from these judgements">
      <ul className="jd-list jd-findings">
        {findings.map((f, i) => {
          const href = transcriptLink(runId, { t_s: f.t_s });
          return (
            <li key={i}>
              <Badge tone={f.hazard ? "bad" : "neutral"} plain>{f.hazard ? "hazard" : f.dimension}</Badge>{" "}
              <span className="mono">{f.mode}.{f.detector}</span>
              <span className="muted"> at {formatDuration(f.t_s)}</span>
              {href && (
                <>
                  {" "}
                  <Link to={href}>transcript</Link>
                </>
              )}
              <div className="jd-ev">{f.evidence}</div>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}
