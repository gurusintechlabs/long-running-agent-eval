import type { Tone } from "../../components";
import type { DisplayEvent } from "./types";

// Pure mapping from a display event to what its card shows. Everything returned is plain strings: the
// card renders them as React text children (payload_preview is raw agent output, UI-5).

export interface Chip {
  text: string;
  tone?: Tone;
  title?: string;
}

export interface CardModel {
  /** Icon name (see icons.tsx). */
  icon: string;
  /** Kind colour class suffix. */
  accent: string;
  chips: Chip[];
  /** Longer text shown clamped under the title (assistant text, counterpart message). */
  text: string | null;
  /** Severity tone for the left border / badge. */
  tone: Tone;
  /** The card is a status/noise line (drawn smaller and muted). */
  quiet: boolean;
}

type Rec = Record<string, unknown>;

export function asRec(v: unknown): Rec {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Rec) : {};
}
function str(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}
function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function severityTone(s: string): Tone {
  if (s === "kill" || s === "violation") return "bad";
  if (s === "warning") return "warn";
  return "neutral";
}

const ICON: Record<string, string> = {
  tool_call: "tool",
  tool_result: "result",
  assistant_text: "chat",
  session: "session",
  test_run: "flask",
  checkpoint: "flag",
  stage: "layers",
  turn: "turn",
  state: "clock",
  run: "play",
  counterpart: "user",
  env: "box",
  budget: "coin",
  guardrail: "shield",
  kill: "stop",
  scorer: "bars",
  folded: "fold",
  usage: "braces",
  raw: "braces",
  generic: "braces",
};

export function iconFor(kind: string): string {
  return ICON[kind] ?? "braces";
}

function shortSha(s: string | null): string | null {
  return s ? s.slice(0, 8) : null;
}

export function cardModel(ev: DisplayEvent, result?: DisplayEvent): CardModel {
  const p = asRec(ev.payload_preview);
  const chips: Chip[] = [];
  let text: string | null = null;
  let tone = severityTone(ev.severity);
  let quiet = false;

  switch (ev.kind) {
    case "tool_call": {
      if (result) {
        const r = asRec(result.payload_preview);
        const err = r.is_error === true || result.severity === "warning";
        chips.push({ text: err ? "error" : "ok", tone: err ? "bad" : "ok" });
        if (err) tone = "warn";
      }
      break;
    }
    case "tool_result": {
      const err = asRec(ev.payload_preview).is_error === true;
      chips.push({ text: err ? "error" : "ok", tone: err ? "bad" : "ok" });
      break;
    }
    case "assistant_text":
      text = str(p.text);
      break;
    case "counterpart":
      text = str(p.text) ?? str(p.message) ?? str(p.body);
      chips.push({ text: ev.type, tone: "info" });
      break;
    case "checkpoint": {
      const k = num(p.k);
      if (k != null) chips.push({ text: `k=${k}`, tone: "info" });
      const sha = shortSha(str(p.head_sha));
      if (sha) chips.push({ text: sha });
      const fin = str(p.final);
      if (fin) chips.push({ text: `final: ${fin}`, tone: "warn" });
      break;
    }
    case "stage": {
      const st = num(p.stage);
      if (st != null) chips.push({ text: `stage ${st}`, tone: "info" });
      const k = str(p.kind);
      if (k) chips.push({ text: k });
      break;
    }
    case "turn":
      chips.push({ text: ev.type === "turn.start" ? "start" : ev.type === "turn.end" ? "end" : ev.type });
      quiet = true;
      break;
    case "state": {
      const from = str(p.from);
      const to = str(p.to);
      if (from && to) chips.push({ text: `${from} → ${to}`, tone: to === "RUNNING" ? "info" : "neutral" });
      quiet = true;
      break;
    }
    case "test_run": {
      const pass = num(p.passed);
      const fail = (num(p.failed) ?? 0) + (num(p.errors) ?? 0);
      if (pass != null) chips.push({ text: `${pass} passed`, tone: "ok" });
      if (fail > 0) chips.push({ text: `${fail} failed`, tone: "bad" });
      break;
    }
    case "guardrail": {
      const rule = str(p.rule_id);
      if (rule) chips.push({ text: rule, tone: severityTone(ev.severity) });
      const act = str(p.action);
      if (act) chips.push({ text: act, tone: act === "kill" ? "bad" : "neutral" });
      const ch = str(p.channel);
      if (ch) chips.push({ text: ch });
      break;
    }
    case "kill": {
      const rule = str(p.rule_id);
      if (rule) chips.push({ text: rule, tone: "bad" });
      const reason = str(p.reason);
      if (reason) chips.push({ text: reason, tone: "bad" });
      const ms = num(p.freeze_latency_ms);
      if (ms != null) chips.push({ text: `frozen in ${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms` });
      break;
    }
    case "scorer": {
      const k = num(p.k);
      if (k != null) chips.push({ text: `k=${k}`, tone: "info" });
      if (p.hazard === true) chips.push({ text: "hazard", tone: "bad" });
      const dim = str(p.dimension);
      if (dim) chips.push({ text: dim });
      if (ev.type === "scorer.done" || ev.type === "scorer.finished") quiet = true;
      break;
    }
    case "budget": {
      const usd = num(p.cost_usd);
      if (usd != null) chips.push({ text: `$${usd.toFixed(2)}`, tone: "warn" });
      break;
    }
    case "env":
      chips.push({ text: ev.type });
      break;
    case "folded": {
      const f = ev.fold;
      if (f) {
        chips.push({ text: `${f.pairs} pause${f.pairs === 1 ? "" : "s"}` });
        if (f.open) chips.push({ text: "silent now", tone: "warn" });
      }
      quiet = true;
      break;
    }
    case "session":
    case "run":
      break;
    default:
      chips.push({ text: ev.type });
  }
  return { icon: iconFor(ev.kind), accent: ev.kind, chips, text, tone, quiet };
}

/** The text shown in the expanded detail: JSON of the payload, capped. Always a string, never HTML. */
export function detailJson(v: unknown, maxChars = 20000): { text: string; cut: number } {
  let s: string;
  try {
    s = JSON.stringify(v, null, 2) ?? "";
  } catch {
    s = String(v);
  }
  if (s.length <= maxChars) return { text: s, cut: 0 };
  return { text: s.slice(0, maxChars), cut: s.length - maxChars };
}

export function fmtOffset(t: number | null | undefined): string {
  if (t == null || !Number.isFinite(t)) return "–";
  const total = Math.max(0, Math.floor(t));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const p2 = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${p2(m)}:${p2(s)}` : `${m}:${p2(s)}`;
}
