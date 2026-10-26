import { useMemo, useState } from "react";
import { testsApi, useAsync, type Flip, type TestsResponse } from "../../../api";
import { IngestButton } from "../../../app/IngestBanner";
import { Badge, Card, EmptyState, ErrorState, LazyChart, Spinner } from "../../../components";
import { formatDuration, formatNumber, shortSha } from "../../../lib/format";
import { formatClock } from "../../../lib/text";
import { usePalette, type Palette } from "../common/colors";
import { Chip, Notice } from "../common/Widgets";
import { HeatmapCanvas, type HoverInfo } from "./HeatmapCanvas";
import { buildRows, cellFlips, tierLabel } from "./heatmapModel";
import { passRateOption, stageOption } from "./testCharts";

const FLIPS_STEP = 100;

export function TestsTab({ runId, onReingest, reingesting }: { runId: string; onReingest: () => void; reingesting: boolean }) {
  const [suite, setSuite] = useState<string | undefined>(undefined);
  const q = useAsync((s) => testsApi.get(runId, suite, s), [runId, suite]);
  if (q.error && !q.data) return <Card><ErrorState title="Could not load test outcomes" error={q.error} onRetry={q.reload} /></Card>;
  if (!q.data) return <Spinner label="Loading test outcomes" />;
  const d = q.data;
  if (!d.ingested) {
    return (
      <Card>
        <div className="not-ingested">
          <div>
            <h2>Test outcomes need ingest</h2>
            <p className="muted">{d.reason}</p>
          </div>
          <IngestButton running={reingesting} onClick={onReingest} />
        </div>
      </Card>
    );
  }
  if (!d.has_outcomes || d.tests.length === 0) {
    return (
      <Card>
        <EmptyState title="No per-test data for this run">
          The run is in the store but has no recorded test outcomes (older runs were ingested without them). Re-ingest after a scorer run to fill this in.
        </EmptyState>
      </Card>
    );
  }
  return <TestsBody d={d} suite={d.suite} onSuite={setSuite} />;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <div className="stat-v">{value}</div>
      <div className="stat-l">{label}</div>
    </div>
  );
}

const pct = (v: number | null | undefined) => (v == null ? "–" : `${(v * 100).toFixed(1)}%`);

function TestsBody({ d, suite, onSuite }: { d: TestsResponse; suite: string; onSuite: (s: string) => void }) {
  const palette = usePalette();
  const [tiers, setTiers] = useState<Set<string> | null>(null);
  const [mode, setMode] = useState<"all" | "flipped" | "failing">("all");
  const [text, setText] = useState("");
  const [hover, setHover] = useState<HoverInfo | null>(null);

  const allTiers = useMemo(() => [...new Set(d.tests.map((t) => tierLabel(t.tier)))].sort((a, b) => Number(a) - Number(b) || a.localeCompare(b)), [d.tests]);
  const tests = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return d.tests.filter((t) => {
      if (tiers && !tiers.has(tierLabel(t.tier))) return false;
      if (needle && !t.id.toLowerCase().includes(needle)) return false;
      if (mode === "flipped") return cellFlips(t.cells).length > 0;
      if (mode === "failing") {
        const last = [...t.cells].reverse().find((c) => c !== "-" && c !== "s");
        return last === "f" || last === "e";
      }
      return true;
    });
  }, [d.tests, tiers, mode, text]);
  const rows = useMemo(() => buildRows(tests), [tests]);
  const s = d.summary;

  const toggleTier = (t: string) => {
    const n = new Set(tiers ?? allTiers);
    if (n.has(t)) n.delete(t);
    else n.add(t);
    setTiers(n.size === allTiers.length ? null : n);
  };

  return (
    <>
      <Card
        title="Test outcomes"
        actions={
          d.suites.length > 1 ? (
            <label className="row" style={{ gap: 6 }}>
              <span className="muted">Suite</span>
              <select className="field" value={suite} onChange={(e) => onSuite(e.target.value)}>
                {d.suites.map((x) => (
                  <option key={x} value={x}>{x}</option>
                ))}
              </select>
            </label>
          ) : undefined
        }
      >
        <div className="stats">
          <Stat label="tests" value={String(d.tests.length)} />
          <Stat label="time points" value={String(d.points.length)} />
          <Stat label="regressions" value={formatNumber(s.regressions)} hint="pass -> fail flips" />
          <Stat label="regressed tests" value={formatNumber(s.regressed_tests)} />
          <Stat label="relapsing" value={formatNumber(s.relapsing_tests)} hint="tests that regressed again after recovering" />
          <Stat label="mean time to regress" value={s.mean_ttfr_s != null ? formatDuration(s.mean_ttfr_s) : "–"} />
          <Stat label="established (final)" value={pct(s.established_final)} hint="pass rate of tests that passed before" />
          <Stat label="overall (final)" value={pct(s.overall_final)} />
        </div>
        {d.tests_truncated && <Notice tone="warn">Only the first 5000 tests are shown.</Notice>}

        <div className="hm-controls">
          <div className="picker" role="group" aria-label="Filter by tier" style={{ marginBottom: 0 }}>
            {allTiers.map((t) => (
              <Chip key={t} on={!tiers || tiers.has(t)} onClick={() => toggleTier(t)}>
                Tier {t}
              </Chip>
            ))}
          </div>
          <select className="field" aria-label="Which tests" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
            <option value="all">All tests</option>
            <option value="flipped">Only tests that flipped</option>
            <option value="failing">Only failing at the end</option>
          </select>
          <input className="field" type="search" placeholder="Filter test id" aria-label="Filter test id" value={text} onChange={(e) => setText(e.target.value)} />
          <span className="muted">{tests.length} shown</span>
        </div>

        <Legend palette={palette} />
        {rows.length === 0 ? (
          <EmptyState title="No tests match these filters" />
        ) : (
          <div className="hm-wrap">
            <HeatmapCanvas rows={rows} points={d.points} palette={palette} onHover={setHover} />
            {hover && <HoverTip h={hover} />}
          </div>
        )}
      </Card>

      <div className="two-col">
        <Card title="Pass rate over time">
          <LazyChart option={passRateOption(d.pass_rates, palette)} height={240} label="Pass rate over time: overall, established and per tier" />
        </Card>
        <Card title="Pass rate at the end of each stage">
          <LazyChart option={stageOption(d.pass_rates, palette)} height={240} label="Pass rate at the end of each stage, overall and established" />
        </Card>
      </div>

      <FlipList flips={d.flips} />
    </>
  );
}

function Legend({ palette }: { palette: Palette }) {
  const items: [string, string][] = [
    ["passed", palette.ok],
    ["failed", palette.bad],
    ["error", palette.warn],
    ["skipped", palette.neutral],
    ["not scored", palette.surface2],
  ];
  return (
    <ul className="hm-legend" aria-label="Legend">
      {items.map(([l, c]) => (
        <li key={l}>
          <span className="chip-swatch" style={{ background: c, border: `1px solid ${palette.border}` }} aria-hidden="true" />
          {l}
        </li>
      ))}
      <li>
        <span className="chip-swatch hm-sw-reg" aria-hidden="true" />
        regression (outlined)
      </li>
      <li>
        <span className="chip-swatch hm-sw-rec" aria-hidden="true" />
        recovery (outlined)
      </li>
      <li className="muted">header: stage bands (s0, s1, ...) and times; diamonds are checkpoints</li>
    </ul>
  );
}

function HoverTip({ h }: { h: HoverInfo }) {
  return (
    <div className="hm-tip" style={{ left: Math.min(h.x + 14, 560), top: h.y + 14 }} role="status">
      <div className="mono hm-tip-id">{h.testId}</div>
      <div>
        <strong>{h.outcome}</strong>
        {h.flip && <> ({h.flip})</>} · tier {tierLabel(h.tier)}
      </div>
      <div className="muted">
        {formatClock(h.point.t_s)} · {h.point.point}
        {h.point.k != null ? ` t${h.point.k}` : ""} · stage {h.point.stage ?? "–"}
        {h.point.sha ? ` · ${shortSha(h.point.sha)}` : ""}
      </div>
    </div>
  );
}

function FlipList({ flips }: { flips: Flip[] }) {
  const [kind, setKind] = useState<"all" | "regression" | "recovery">("regression");
  const [shown, setShown] = useState(FLIPS_STEP);
  const rows = useMemo(() => flips.filter((f) => kind === "all" || f.kind === kind), [flips, kind]);
  return (
    <Card title={`Flips (${rows.length})`}>
      <div className="picker" role="group" aria-label="Flip kind">
        {(["regression", "recovery", "all"] as const).map((k) => (
          <Chip key={k} on={kind === k} onClick={() => { setKind(k); setShown(FLIPS_STEP); }}>
            {k === "all" ? "All flips" : k === "regression" ? "Regressions" : "Recoveries"}
          </Chip>
        ))}
      </div>
      {rows.length === 0 ? (
        <p className="muted">No flips of this kind.</p>
      ) : (
        <ul className="flips">
          {rows.slice(0, shown).map((f, i) => (
            <li key={`${f.test_id}-${f.t_s}-${i}`} className="flip">
              <span className="mono inc-time">{formatClock(f.t_s)}</span>
              <Badge tone={f.kind === "regression" ? "bad" : "ok"} plain>{f.kind}</Badge>
              <span className="muted">tier {tierLabel(f.tier)}</span>
              <span className="mono flip-id">{f.test_id}</span>
            </li>
          ))}
        </ul>
      )}
      {rows.length > shown && (
        <button type="button" className="btn" onClick={() => setShown(shown + FLIPS_STEP)}>
          Show {Math.min(FLIPS_STEP, rows.length - shown)} more
        </button>
      )}
    </Card>
  );
}
