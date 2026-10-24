import type { ReactNode } from "react";
import type { RunDetail } from "../../api";
import { Badge, Card, StateBadge } from "../../components";
import { EMPTY, formatDateTime, formatDuration, formatTokens, formatUsd, shortSha } from "../../lib/format";
import { RunActions } from "../launch";
import { runDuration } from "../runs/filter";

function Item({ label, children, title }: { label: string; children: ReactNode; title?: string }) {
  return (
    <div className="kv" title={title}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function safeModeLabel(v: unknown): { text: string; reason?: string } {
  if (v === undefined || v === null) return { text: "not recorded" };
  if (typeof v === "boolean") return { text: v ? "on" : "off" };
  if (typeof v === "object") {
    const o = v as { enabled?: unknown; reason?: unknown };
    return { text: o.enabled === true ? "on" : o.enabled === false ? "off" : "unknown", reason: typeof o.reason === "string" ? o.reason : undefined };
  }
  return { text: String(v) };
}

export function RunHeader({ detail }: { detail: RunDetail }) {
  const { run, manifest: m } = detail;
  const end = m.end ?? null;
  const safe = safeModeLabel(m.safe_mode);
  const reasons = [end?.end_reason, end?.censored_reason, end?.error].filter((x): x is string => !!x);
  return (
    <Card className="run-header">
      <div className="rh-top">
        <div>
          <h1 className="mono rh-title">{run.run_id}</h1>
          <div className="row rh-badges">
            <StateBadge state={run.state} live={run.live} />
            {run.live && <span className="muted">running now</span>}
            {run.resumed && <Badge tone="neutral" plain>resumed</Badge>}
            {!run.ingested && <Badge tone="warn" plain title="Metrics and hazards need lrae ingest">not ingested</Badge>}
          </div>
        </div>
        <RunActions detail={detail} />
      </div>
      <dl className="kv-grid">
        <Item label="Experiment">
          {run.experiment_id ?? EMPTY}
          {run.config != null && <span className="muted"> {"·"} config {run.config}</span>}
          {run.repeat != null && <span className="muted"> {"·"} repeat {run.repeat}</span>}
        </Item>
        <Item label="Model">
          <span className="mono">{run.model ?? EMPTY}</span>
        </Item>
        <Item label="Claude Code CLI">
          <span className="mono">{run.claude_code_version ?? EMPTY}</span>
        </Item>
        <Item label="Spec hash" title={m.spec_hash}>
          <span className="mono">{shortSha(m.spec_hash, 12)}</span>
        </Item>
        <Item label="Seed commit" title={m.seed_commit}>
          <span className="mono">{shortSha(m.seed_commit, 12)}</span>
        </Item>
        <Item label="Isolation mode">{run.isolation_mode ?? EMPTY}</Item>
        <Item label="Safe mode" title={safe.reason}>
          {safe.text}
          {safe.reason && <span className="muted"> (why: {safe.reason})</span>}
        </Item>
        <Item label="Runtime">{run.runtime ?? EMPTY}</Item>
        <Item label="Started">{formatDateTime(run.start_epoch)}</Item>
        <Item label="Duration">{formatDuration(runDuration(run))}</Item>
        <Item label="Est. cost" title="Estimated, API-equivalent (D-16): not a bill">
          {formatUsd(run.cost_usd)} <span className="muted">estimated (API-equivalent)</span>
        </Item>
        <Item label="Tokens">{formatTokens(run.tokens)}</Item>
        <Item label="End state">
          {end ? (end.state ?? run.state ?? EMPTY) : run.live ? "still running" : "no end recorded"}
        </Item>
        <Item label="End reason">{reasons.length ? reasons.join(" · ") : EMPTY}</Item>
        <Item label="Time to first hazard">{run.ingested ? formatDuration(run.ttfh_s) : EMPTY}</Item>
      </dl>
    </Card>
  );
}
