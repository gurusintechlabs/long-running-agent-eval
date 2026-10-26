import { useMemo, useState } from "react";
import { ApiError, api, compareApi, useAsync, type SurvivalGroup } from "../../api";
import { IngestButton, useIngest } from "../../app/IngestBanner";
import { Card, ErrorState, LazyChart, Spinner, useChartTheme } from "../../components";
import { buildSurvivalOption } from "./charts";

function mins(s: number | null | undefined): string {
  return s == null ? "not reached" : `${(s / 60).toFixed(1)} min`;
}

export function censorText(g: SurvivalGroup): string {
  const parts = Object.entries(g.censored_by_reason).map(([k, v]) => `${v} ${k}`);
  return g.censored === 0 ? "0" : `${g.censored} (${parts.join(", ")})`;
}

export function SurvivalSummary({ groups }: { groups: SurvivalGroup[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="visually-hidden">Survival summary per task class and config</caption>
        <thead>
          <tr>
            <th scope="col">Task class / config</th>
            <th scope="col" className="num">n</th>
            <th scope="col" className="num">Hazards</th>
            <th scope="col">Censored</th>
            <th scope="col" className="num">Median</th>
            <th scope="col">Median 95% CI (bootstrap)</th>
            <th scope="col">Operating limit (D-11)</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <tr key={`${g.task_class}/${g.config}`}>
              <th scope="row">{g.label}</th>
              <td className="num">{g.n}</td>
              <td className="num">{g.events}</td>
              <td>{censorText(g)}</td>
              <td className="num">{g.available ? (g.median_text ?? mins(g.median_s)) : "not available"}</td>
              <td>
                {g.available && g.median_ci_boot_s
                  ? `${mins(g.median_ci_boot_s[0])} to ${g.median_ci_hi_not_reached ? "not reached" : mins(g.median_ci_boot_s[1])}`
                  : "not available"}
              </td>
              <td className="sv-headline">{g.headline_available ? g.headline_text : "not available"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SurvivalPanel({ initialExperiment }: { initialExperiment: string | null }) {
  const theme = useChartTheme();
  const expQ = useAsync((s) => api.experiments(s), []);
  const [pick, setPick] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const ing = useIngest();

  const experiments = expQ.data?.experiments ?? [];
  const experiment = pick ?? initialExperiment ?? experiments[0]?.experiment_id ?? null;
  const survQ = useAsync(
    (s) => (experiment ? compareApi.survival(experiment, undefined, s) : Promise.resolve(null)),
    [experiment],
  );
  const groups = useMemo(() => (survQ.data?.groups ?? []).filter((g) => !hidden.has(`${g.task_class}/${g.config}`)), [survQ.data, hidden]);
  const option = useMemo(() => buildSurvivalOption(groups, theme), [groups, theme]);
  const notFound = survQ.error instanceof ApiError && survQ.error.status === 404;

  return (
    <Card title="Survival (time to first hazard)">
      <div className="ov-controls">
        <label className="tb-field">
          <span className="tb-label">Experiment</span>
          <select className="field" value={experiment ?? ""} onChange={(e) => (setPick(e.target.value), setHidden(new Set()))} aria-label="Experiment">
            {experiments.map((e) => (
              <option key={e.experiment_id} value={e.experiment_id}>
                {e.experiment_id} ({e.runs} run{e.runs === 1 ? "" : "s"})
              </option>
            ))}
          </select>
        </label>
        {(survQ.data?.groups.length ?? 0) > 1 && (
          <div className="picker" role="group" aria-label="Configs shown">
            {survQ.data?.groups.map((g) => {
              const key = `${g.task_class}/${g.config}`;
              const on = !hidden.has(key);
              return (
                <button
                  key={key}
                  type="button"
                  className={`chip${on ? " chip-on" : ""}`}
                  aria-pressed={on}
                  onClick={() => setHidden((h) => { const n = new Set(h); if (on) n.add(key); else n.delete(key); return n; })}
                >
                  {g.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
      {!experiment ? (
        <p className="muted">There are no experiments yet.</p>
      ) : survQ.loading ? (
        <Spinner label="Loading survival" />
      ) : notFound ? (
        <div className="not-ingested">
          <p className="muted">This experiment is not in the metrics store, so there is no survival curve. Ingest to compute one.</p>
          <IngestButton running={ing.running} onClick={() => void ing.run()} />
        </div>
      ) : survQ.error ? (
        <ErrorState title="Could not load survival" error={survQ.error} onRetry={survQ.reload} />
      ) : survQ.data && survQ.data.groups.length === 0 ? (
        <p className="muted">{survQ.data.note ?? "No runs in the survival set."}</p>
      ) : survQ.data ? (
        <>
          <LazyChart option={option} height={340} label={`Kaplan-Meier survival for experiment ${experiment}`} />
          <p className="muted chart-note">
            Step curve = Kaplan-Meier estimate, shaded band = 95% confidence interval, tick marks = censored runs (budget, deadline or interruption),
            dotted vertical line = operating limit (D-11). Computed by <span className="mono">analysis/survival.py</span>.
            {Object.keys(survQ.data.excluded).length > 0 &&
              ` Excluded from survival: ${Object.entries(survQ.data.excluded).map(([k, v]) => `${v} ${k}`).join(", ")}.`}
          </p>
          <SurvivalSummary groups={groups} />
          {survQ.data.groups.some((g) => g.n < 5) && (
            <p className="muted chart-note">Small samples (n &lt; 5) give very wide intervals; read medians and limits as indicative only.</p>
          )}
        </>
      ) : null}
    </Card>
  );
}
