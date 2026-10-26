import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { timelineApi, useAsync, type TimelineResponse } from "../../../api";
import { Badge, Card, EmptyState, ErrorState, LazyChart, Spinner } from "../../../components";
import { formatUsd } from "../../../lib/format";
import { clip, formatClock, useStable } from "../../../lib/text";
import { usePalette } from "../common/colors";
import { Chip, Notice } from "../common/Widgets";
import { buildEvents, buildTimelineOption, clickLink, LANES, type Lane, type TlEvent } from "./timelineModel";

const POLL_MS = 10000;
const SHOW_STEP = 100;

export function TimelineTab({ runId, live }: { runId: string; live: boolean }) {
  const q = useAsync((s) => timelineApi.get(runId, s), [runId], () => (live ? POLL_MS : null));
  const data = useStable(q.data);
  if (q.error && !data) return <Card><ErrorState title="Could not load the timeline" error={q.error} onRetry={q.reload} /></Card>;
  if (!data) return <Spinner label="Loading timeline" />;
  return <TimelineBody tl={data} />;
}

function Summary({ tl }: { tl: TimelineResponse }) {
  const g = tl.guardrail;
  const tone = g.status === "killed" || g.status === "violations" ? "bad" : g.status === "warnings" ? "warn" : "ok";
  return (
    <div className="tl-summary">
      <span>
        Guardrail <Badge tone={tone}>{g.status}</Badge>
      </span>
      <span>
        {g.violations_total} violation{g.violations_total === 1 ? "" : "s"}
        {g.violations.length < g.violations_total && <span className="muted"> (showing {g.violations.length})</span>}
      </span>
      <span>
        {tl.behavior_total} behaviour event{tl.behavior_total === 1 ? "" : "s"}
        {tl.behavior.length < tl.behavior_total && <span className="muted"> (showing {tl.behavior.length})</span>}
      </span>
      <span>{tl.hazards.length} hazard{tl.hazards.length === 1 ? "" : "s"}</span>
      <span>{tl.compactions.length} compaction{tl.compactions.length === 1 ? "" : "s"}</span>
      {g.kill && (
        <span>
          Kill <Badge tone="bad">{g.kill.rule_id}</Badge> at {formatClock(g.kill.t_s)}
        </span>
      )}
      {g.budget?.cost_usd != null && <span>Budget stop at {formatUsd(g.budget.cost_usd)}</span>}
      {g.telemetry_stalls && g.telemetry_stalls.count > 0 && <span>{g.telemetry_stalls.count} telemetry stalls</span>}
      <span className="muted" title="Cost is estimated, API-equivalent (D-16), one point per checkpoint">
        counters from {tl.source_of_counters}
      </span>
    </div>
  );
}

function TimelineBody({ tl }: { tl: TimelineResponse }) {
  const palette = usePalette();
  const navigate = useNavigate();
  const events = useMemo(() => buildEvents(tl), [tl]);
  const option = useMemo(() => buildTimelineOption(tl, palette, events), [tl, palette, events]);
  const [lanes, setLanes] = useState<Set<Lane>>(new Set(["Hazards", "Behaviour", "Guardrail", "Compactions"]));
  const [shown, setShown] = useState(SHOW_STEP);

  const rows = useMemo(() => events.filter((e) => lanes.has(e.lane)), [events, lanes]);
  const toggle = (l: Lane) => {
    const n = new Set(lanes);
    if (n.has(l)) n.delete(l);
    else n.add(l);
    setLanes(n);
    setShown(SHOW_STEP);
  };
  const counts = (l: Lane) => events.filter((e) => e.lane === l).length;

  if (tl.checkpoints.length === 0 && events.length === 0) {
    return <Card><EmptyState title="Nothing on the timeline yet">The first checkpoint is taken at the configured interval.</EmptyState></Card>;
  }

  return (
    <>
      <Card title="Run timeline">
        <Summary tl={tl} />
        <div className="tl-chart">
          <LazyChart
            option={option}
            height={500}
            label="Run timeline: cumulative estimated cost and context fill per checkpoint, with lanes for checkpoints, stages, compactions, hazards, behaviour events and guardrail violations. Use the incident list below for a keyboard-accessible version."
            onClick={(p) => {
              const link = clickLink(p.data);
              if (link) navigate(link);
            }}
          />
        </div>
        <p className="muted chart-note">
          Click a marker to open the matching transcript window. Drag the slider or scroll to zoom; the toolbox zooms to a dragged range.
          Click legend entries to hide a lane. Cost and context fill are sampled per checkpoint.
        </p>
      </Card>

      <Card title={`Incidents (${rows.length})`}>
        <div className="picker" role="group" aria-label="Choose incident lanes">
          {LANES.filter((l) => counts(l) > 0).map((l) => (
            <Chip key={l} on={lanes.has(l)} onClick={() => toggle(l)}>
              {l} <span className="muted">{counts(l)}</span>
            </Chip>
          ))}
        </div>
        {rows.length === 0 ? (
          <p className="muted">No events in the chosen lanes.</p>
        ) : (
          <ul className="incidents">
            {rows.slice(0, shown).map((e, i) => (
              <Incident key={`${e.lane}-${e.t}-${i}`} e={e} />
            ))}
          </ul>
        )}
        {rows.length > shown && (
          <button type="button" className="btn" onClick={() => setShown(shown + SHOW_STEP)}>
            Show {Math.min(SHOW_STEP, rows.length - shown)} more
          </button>
        )}
        {tl.guardrail.by_rule.length > 0 && (
          <div className="rules">
            <h3>Violations by rule</h3>
            <ul>
              {tl.guardrail.by_rule.map((r) => (
                <li key={r.rule_id}>
                  <span className="mono">{r.rule_id}</span> {r.count} <span className="muted">({r.severity}, {r.action}{r.kills ? `, ${r.kills} kill` : ""})</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {tl.guardrail.violations_total > tl.guardrail.violations.length && (
          <Notice tone="info">Showing the first {tl.guardrail.violations.length} of {tl.guardrail.violations_total} violations (server cap).</Notice>
        )}
      </Card>
    </>
  );
}

const TONE = { ok: "ok", warn: "warn", bad: "bad", info: "info", neutral: "neutral" } as const;

function Incident({ e }: { e: TlEvent }) {
  return (
    <li className="incident">
      <span className="inc-time mono">{formatClock(e.t)}</span>
      <Badge tone={TONE[e.tone]} plain>{e.lane}</Badge>
      <span className="inc-body">
        <strong>{e.title}</strong>
        {e.detail[0] && <span className="muted"> {clip(e.detail[0], 220)}</span>}
      </span>
      {e.link && (
        <Link to={e.link} className="inc-open">
          Open
        </Link>
      )}
    </li>
  );
}
