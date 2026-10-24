import { useCallback, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { api, compareApi, useAsync } from "../../api";
import { useDataVersion } from "../../app/DataVersion";
import { IngestButton, useIngest } from "../../app/IngestBanner";
import { Card, EmptyState, ErrorState, Spinner } from "../../components";
import { DeltaTable, HazardTable } from "./DeltaTable";
import { OverlayCharts } from "./OverlayCharts";
import { MAX_COMPARE, RunPicker } from "./RunPicker";
import { SurvivalPanel } from "./SurvivalPanel";
import "./compare.css";

const ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

export function parseRuns(param: string | null): string[] {
  const ids = (param ?? "").split(",").map((s) => s.trim()).filter((s) => ID.test(s));
  return [...new Set(ids)].slice(0, MAX_COMPARE);
}

export function CompareView() {
  const { version } = useDataVersion();
  const [params, setParams] = useSearchParams();
  const selected = useMemo(() => parseRuns(params.get("runs")), [params]);
  const runsQ = useAsync((s) => api.runs(s), [version]);
  const ing = useIngest();

  useEffect(() => {
    document.title = "Compare · LRAE";
  }, []);

  const setSelected = useCallback(
    (ids: string[]) => {
      setParams(ids.length ? { runs: ids.join(",") } : {}, { replace: true });
    },
    [setParams],
  );

  const key = selected.join(",");
  const cmpQ = useAsync((s) => (selected.length ? compareApi.compare(selected, s) : Promise.resolve(null)), [key, version]);
  const runs = runsQ.data?.runs ?? [];
  const firstExperiment = runs.find((r) => r.run_id === selected[0])?.experiment_id ?? null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Compare</h1>
          <div className="page-sub">Overlay runs (metrics, hazards, cost, context fill) and read the survival curve of an experiment.</div>
        </div>
      </div>

      {runsQ.error && !runsQ.data ? (
        <Card>
          <ErrorState title="Could not load runs" error={runsQ.error} onRetry={runsQ.reload} />
        </Card>
      ) : (
        <RunPicker runs={runs} selected={selected} onChange={setSelected} />
      )}

      {selected.length === 0 ? (
        <Card>
          <EmptyState title="Pick runs to compare">Tick two or more runs above (or open Compare from a link with ?runs=id1,id2). The survival curve below does not need a selection.</EmptyState>
        </Card>
      ) : cmpQ.loading ? (
        <Spinner label="Loading comparison" />
      ) : cmpQ.error ? (
        <Card>
          <ErrorState title="Could not load the comparison" error={cmpQ.error} onRetry={cmpQ.reload} />
        </Card>
      ) : cmpQ.data ? (
        <>
          {cmpQ.data.not_ingested.length > 0 && (
            <Card className="card-warn">
              <div className="not-ingested">
                <div>
                  <strong>
                    {cmpQ.data.not_ingested.length === cmpQ.data.runs.length ? "None of these runs is" : `${cmpQ.data.not_ingested.length} of these runs are`} in the metrics store.
                  </strong>
                  <p className="muted">
                    Not ingested: <span className="mono">{cmpQ.data.not_ingested.join(", ")}</span>. They show only their summary and checkpoint times; metrics, hazards and
                    cost series appear after a re-ingest.
                  </p>
                </div>
                <IngestButton running={ing.running} onClick={() => void ing.run()} label="Ingest now" />
              </div>
            </Card>
          )}
          {selected.length === 1 && <p className="muted">One run selected: tick another to see differences.</p>}
          <OverlayCharts data={cmpQ.data} />
          <DeltaTable data={cmpQ.data} />
          <HazardTable data={cmpQ.data} />
        </>
      ) : null}

      <SurvivalPanel key={firstExperiment ?? "none"} initialExperiment={firstExperiment} />
    </>
  );
}
