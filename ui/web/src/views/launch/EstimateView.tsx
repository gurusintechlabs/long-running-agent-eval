import type { ReactNode } from "react";
import type { PreviewResponse } from "../../api";
import { Badge } from "../../components";
import { EMPTY, formatTokens, formatUsd, shortSha } from "../../lib/format";

/** Conflicts, blockers and warnings come as strings or small objects: always shown as text. */
export function itemText(x: unknown): string {
  if (typeof x === "string") return x;
  if (x && typeof x === "object") {
    const o = x as Record<string, unknown>;
    const msg = o.message ?? o.detail ?? o.reason;
    if (typeof msg === "string") return typeof o.code === "string" ? `${o.code}: ${msg}` : msg;
    return JSON.stringify(x);
  }
  return String(x);
}

function mins(v: number | null | undefined): string {
  if (v == null) return EMPTY;
  return v >= 120 ? `${(v / 60).toFixed(1)} h (${v} min)` : `${v} min`;
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="kv">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Issues({ title, items, tone }: { title: string; items: unknown[]; tone: "bad" | "warn" }) {
  if (!items.length) return null;
  return (
    <div className={`issues issues-${tone}`} role={tone === "bad" ? "alert" : "status"}>
      <strong>{title}</strong>
      <ul>
        {items.map((x, i) => (
          <li key={i}>{itemText(x)}</li>
        ))}
      </ul>
    </div>
  );
}

/** The server-computed estimate, shown exactly as received. Nothing here is computed by the client. */
export function EstimateView({ preview }: { preview: PreviewResponse }) {
  const e = preview.estimate;
  const resume = e.kind === "resume";
  const real = e.real_spend;
  return (
    <div className="estimate">
      <div className={`spend-banner ${real ? "spend-real" : "spend-none"}`} role={real ? "alert" : "status"}>
        <div className="spend-head">
          {real ? (
            <Badge tone="bad">REAL SPEND</Badge>
          ) : (
            <Badge tone="ok">No spend</Badge>
          )}
          <strong>
            {real
              ? `This ${resume ? "resume" : "launch"} uses the real claude_code runtime and spends real money.`
              : `Scripted runtime: no model calls, no spend.`}
          </strong>
        </div>
        {real && (
          <ul className="spend-reasons">
            {(e.spend_reasons ?? []).map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        )}
        <div className="spend-figures">
          <div>
            <div className="spend-label">Max spend (cap)</div>
            <div className="spend-big" data-testid="max-spend">
              {formatUsd(e.max_spend_usd)}
            </div>
          </div>
          <div>
            <div className="spend-label">Runs</div>
            <div className="spend-big" data-testid="run-count">
              {resume ? 1 : e.run_count ?? EMPTY}
            </div>
          </div>
          <div>
            <div className="spend-label">Model</div>
            <div className="spend-mid mono">{e.model ?? (real ? EMPTY : "none (scripted)")}</div>
          </div>
        </div>
        <p className="muted spend-note">
          Figures are API-equivalent estimates computed by the server from the spec (D-16). The real cost is subscription usage, not an invoice.
        </p>
      </div>

      <Issues title="Blockers" items={preview.blockers} tone="bad" />
      <Issues title="Conflicts" items={preview.conflicts} tone="bad" />
      <Issues title="Warnings" items={preview.warnings} tone="warn" />

      <dl className="kv-grid est-grid">
        <Item label="Experiment">{e.experiment_id ?? EMPTY}</Item>
        <Item label="Spec">
          <span className="mono">{e.spec_path ?? EMPTY}</span>
        </Item>
        <Item label="Spec hash">
          <span className="mono" title={e.spec_hash}>
            {shortSha(e.spec_hash, 16)}
          </span>
        </Item>
        <Item label="Agent runtime">{e.runtime ?? EMPTY}</Item>
        <Item label="Judge">
          {e.judge_runtime ?? EMPTY}
          {e.judge_model && <span className="muted"> {"·"} {e.judge_model}</span>}
        </Item>
        <Item label="Claude Code CLI">
          <span className="mono">{e.claude_code_version ?? EMPTY}</span>
        </Item>
        {resume && <Item label="Resume from">{e.from ?? EMPTY}</Item>}
        {resume && <Item label="Remaining checkpoints">{e.remaining_checkpoints ?? EMPTY}</Item>}
        {!resume && <Item label="Configs">{(e.configs ?? []).join(", ") || EMPTY}</Item>}
        {!resume && <Item label="Repeats">{(e.repeats ?? []).join(", ") || EMPTY}</Item>}
        <Item label="Per-run USD cap">{formatUsd(e.per_run_usd)}</Item>
        <Item label="Experiment USD cap">{formatUsd(e.experiment_usd)}</Item>
        <Item label="Spent so far">{formatUsd(e.spent_so_far_usd)}</Item>
        <Item label="Token cap (per run)">{e.per_run_tokens == null ? "none" : formatTokens(e.per_run_tokens)}</Item>
        <Item label="Duration">{mins(e.duration_min)}</Item>
        <Item label="Checkpoints">
          {e.checkpoint_count ?? EMPTY}
          {e.checkpoint_interval_min != null && <span className="muted"> {"·"} every {e.checkpoint_interval_min} min</span>}
        </Item>
        <Item label="Wall-clock limit">{mins(e.max_wall_clock_min)}</Item>
      </dl>

      {!resume && (e.run_ids?.length ?? 0) > 0 && (
        <div>
          <div className="est-sub">Run ids ({e.run_ids?.length})</div>
          <ul className="run-id-list">
            {e.run_ids?.map((id) => (
              <li key={id} className="mono">
                {id}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <div className="est-sub">Pre-flight checks</div>
        <ul className="checks">
          {preview.checks.map((c, i) => (
            <li key={i} className={c.ok ? "check-ok" : "check-fail"}>
              <Badge tone={c.ok ? "ok" : "bad"} plain>
                {c.ok ? "pass" : "FAIL"}
              </Badge>
              <span>{c.name}</span>
              {c.detail && <span className="muted mono"> {c.detail}</span>}
            </li>
          ))}
        </ul>
        <p className="muted spend-note">
          This is a no-spend check; the harness runs its own pre-flight again (CLI version, probe) at the start of the run and fails the run if it does not pass.
        </p>
      </div>
    </div>
  );
}
