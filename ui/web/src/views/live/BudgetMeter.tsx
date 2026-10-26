import { formatDuration, formatTokens, formatUsd } from "../../lib/format";
import type { BudgetMeterData, Level } from "./types";

// Budget meters: cost against per_run_usd, tokens against per_run_tokens, wall-clock against the duration cap.
// The server decides the level (ok below 75 %, amber from 75 %, red from 90 %); the label always says it in
// words so colour is never the only cue.

export function levelFor(fraction: number | null | undefined, th = { amber: 0.75, red: 0.9 }): Level {
  if (fraction == null) return "ok";
  return fraction >= th.red ? "red" : fraction >= th.amber ? "amber" : "ok";
}

const LEVEL_TEXT: Record<string, string> = { ok: "within budget", amber: "above 75%", red: "above 90%" };

function Meter({ label, used, cap, fraction, level }: { label: string; used: string; cap: string | null; fraction: number | null; level: Level }) {
  const pct = fraction == null ? null : Math.round(fraction * 100);
  const width = fraction == null ? 0 : Math.min(100, Math.max(0, fraction * 100));
  const text = fraction == null ? "no cap set" : fraction >= 1 ? `cap reached (${pct}%)` : `${pct}% · ${LEVEL_TEXT[level] ?? level}`;
  return (
    <div className={`bm bm-${level}`}>
      <div className="bm-head">
        <span className="bm-label">{label}</span>
        <span className="bm-figures">
          <strong>{used}</strong>
          {cap && <span className="muted"> of {cap}</span>}
        </span>
      </div>
      <div
        className="bm-track"
        role="meter"
        aria-label={`${label} budget`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct ?? 0}
        aria-valuetext={`${used}${cap ? ` of ${cap}` : ""}, ${text}`}
      >
        <div className="bm-fill" style={{ width: `${width}%` }} />
        <span className="bm-tick" style={{ left: "75%" }} />
        <span className="bm-tick bm-tick-red" style={{ left: "90%" }} />
      </div>
      <div className="bm-note">{text}</div>
    </div>
  );
}

export function BudgetMeter({
  meter,
  costUsd,
  tokens,
  elapsedS,
}: {
  meter: BudgetMeterData;
  costUsd?: number | null;
  tokens?: number | null;
  elapsedS?: number | null;
}) {
  const th = meter.thresholds ?? { amber: 0.75, red: 0.9 };
  const usd = costUsd ?? meter.cost_usd ?? null;
  const tok = tokens ?? meter.tokens ?? null;
  const capS = meter.duration_min != null ? meter.duration_min * 60 : null;
  const timeFrac = meter.time_fraction ?? (elapsedS != null && capS ? elapsedS / capS : null);
  return (
    <div className="bm-grid">
      <Meter
        label="Cost"
        used={usd != null ? `$${usd.toFixed(2)}` : "–"}
        cap={meter.per_run_usd != null ? formatUsd(meter.per_run_usd) : null}
        fraction={meter.usd_fraction}
        level={meter.level}
      />
      <Meter
        label="Tokens"
        used={formatTokens(tok)}
        cap={meter.per_run_tokens != null ? formatTokens(meter.per_run_tokens) : null}
        fraction={meter.tokens_fraction}
        level={levelFor(meter.tokens_fraction, th)}
      />
      <Meter
        label="Wall-clock"
        used={formatDuration(elapsedS ?? (timeFrac != null && capS ? timeFrac * capS : null))}
        cap={capS != null ? formatDuration(capS) : null}
        fraction={timeFrac}
        level={meter.time_level ?? levelFor(timeFrac, th)}
      />
      {meter.cap_eta_s != null && meter.cap_eta_s > 0 && !meter.exhausted && (
        <div className="bm-eta muted">At the recent burn rate the cost cap is reached in about {formatDuration(meter.cap_eta_s)}.</div>
      )}
    </div>
  );
}
