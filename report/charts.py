"""Deterministic matplotlib charts (Agg, fixed sizes, no dates in PNG metadata).

Every function takes plain data (see ``report.dashboard`` for how it is gathered from SQLite),
writes one PNG and returns its path. Time axes are in minutes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from analysis.degradation import FAILING, Flip, Matrix, RatePoint
from analysis.survival import KM
from analysis.trends import CORE_METRICS, Series, median_by_k

# Okabe-Ito: colour-blind safe, distinct in light and print.
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#7a7a7a"]
HAZARD_COLOR = {"quality": "#D55E00", "context": "#CC79A7", "cost": "#E69F00", "safety": "#b00020",
                "security": "#56B4E9", "integrity": "#009E73"}
METRIC_LABEL = {"P": "P hidden pass rate", "R": "R regressions", "D": "D defect density",
                "C": "C constraint violations", "W": "W repeat-work ratio", "X": "X contradictions",
                "S": "S cost / accepted commit ($, est.)"}
INK, FAINT = "#222222", "#bdbdbd"


def _save(fig: Figure, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    FigureCanvasAgg(fig)
    fig.savefig(out, format="png", dpi=100, metadata={"Software": None})
    return out


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(True, color="#ececec", linewidth=0.6)
    ax.tick_params(labelsize=8, colors=INK)


def _empty(ax, msg: str) -> None:
    ax.text(0.5, 0.5, msg, ha="center", va="center", transform=ax.transAxes, color="#777", fontsize=9)
    ax.set_xticks([])
    ax.set_yticks([])


def survival_chart(curves: list[dict], out: Path, *, title: str = "Survival: runs without a hazard (Kaplan-Meier, 95% CI)",
                   target: float = 0.8) -> Path:
    """``curves``: dicts ``{label, km: KM, headline: float | None}`` (times in seconds)."""
    fig = Figure(figsize=(7.0, 4.0))
    ax = fig.add_subplot(111)
    _style(ax)
    for i, c in enumerate(curves):
        km: KM = c["km"]
        col = PALETTE[i % len(PALETTE)]
        x = np.concatenate([[0.0], km.times]) / 60.0
        ax.step(x, np.concatenate([[1.0], km.surv]), where="post", color=col, lw=2, label=c["label"])
        ax.fill_between(x, np.concatenate([[1.0], km.lower]), np.concatenate([[1.0], km.upper]),
                        step="post", color=col, alpha=0.15, lw=0)
        cens = km.times[(km.n_event == 0)] / 60.0
        if cens.size:
            ax.plot(cens, [km.survival_at(t * 60.0) for t in cens], "|", color=col, ms=9)
        if c.get("headline") is not None:
            ax.axvline(c["headline"] / 60.0, color=col, ls="--", lw=1)
            ax.annotate("operating limit", (c["headline"] / 60.0, 0.03), fontsize=8, color=col,
                        rotation=90, va="bottom", ha="right")
    ax.axhline(target, color="#888", ls=":", lw=1)
    ax.text(0.99, target + 0.01, f"target {target:g}", transform=ax.get_yaxis_transform(),
            ha="right", fontsize=8, color="#666")
    ax.set_ylim(-0.02, 1.05)
    ax.set_xlim(left=0)
    ax.set_xlabel("run time (min)", fontsize=9)
    ax.set_ylabel("S(t), fraction without hazard", fontsize=9)
    ax.set_title(title, fontsize=10, loc="left", color=INK)
    if curves:
        ax.legend(fontsize=8, frameon=False, loc="lower left")
    fig.tight_layout()
    return _save(fig, out)


def metric_strips(series: list[Series], out: Path) -> Path:
    """Seven small multiples (the core metrics) vs runtime: faint per-run lines + across-run median."""
    fig = Figure(figsize=(10.0, 7.2))
    for i, name in enumerate(CORE_METRICS):
        ax = fig.add_subplot(4, 2, i + 1)
        _style(ax)
        mine = [s for s in series if s.name == name]
        for s in mine:
            ax.plot(np.array(s.t_s) / 60.0, s.value, color=FAINT, lw=1, marker="o", ms=2.5)
        ks, tm, vm = median_by_k(series, name)
        if vm:
            ax.plot(np.array(tm) / 60.0, vm, color=PALETTE[0], lw=2.2, marker="o", ms=4, label="median")
        elif not mine:
            _empty(ax, "no data")
        ax.set_title(METRIC_LABEL[name], fontsize=9, loc="left", color=INK)
        if i >= 5:
            ax.set_xlabel("run time (min)", fontsize=8)
    ax = fig.add_subplot(4, 2, 8)
    ax.axis("off")
    ax.plot([], [], color=FAINT, lw=1, label="individual runs")
    ax.plot([], [], color=PALETTE[0], lw=2.2, label="median across runs")
    ax.legend(fontsize=9, frameon=False, loc="center")
    fig.tight_layout()
    return _save(fig, out)


def cost_chart(cost: dict[str, tuple[list[float], list[float]]], out: Path) -> Path:
    """Cumulative estimated (API-equivalent) cost vs runtime, one line per run."""
    fig = Figure(figsize=(7.0, 3.6))
    ax = fig.add_subplot(111)
    _style(ax)
    for i, (rid, (t, v)) in enumerate(sorted(cost.items())):
        ax.plot(np.array(t) / 60.0, v, color=PALETTE[i % len(PALETTE)], lw=1.8, marker="o", ms=3,
                label=rid)
    if not cost:
        _empty(ax, "no cost data")
    else:
        ax.legend(fontsize=7, frameon=False)
    ax.set_xlabel("run time (min)", fontsize=9)
    ax.set_ylabel("cumulative cost, estimated (API-equivalent) $", fontsize=9)
    ax.set_title("Cost vs runtime (estimated, subscription login)", fontsize=10, loc="left", color=INK)
    fig.tight_layout()
    return _save(fig, out)


def context_chart(fill: dict[str, tuple[list[float], list[float]]], out: Path, *,
                  compactions: dict[str, list[float]] | None = None,
                  hazards: dict[str, list[tuple[float, str]]] | None = None) -> Path:
    """Context fill (fraction of window) vs runtime; compactions (triangles) and hazards (lines)."""
    compactions, hazards = compactions or {}, hazards or {}
    fig = Figure(figsize=(7.0, 3.8))
    ax = fig.add_subplot(111)
    _style(ax)
    for i, (rid, (t, v)) in enumerate(sorted(fill.items())):
        col = PALETTE[i % len(PALETTE)]
        ax.plot(np.array(t) / 60.0, v, color=col, lw=1.8, marker="o", ms=3, label=rid)
        for tc in compactions.get(rid, []):
            ax.plot([tc / 60.0], [0.02], "^", color=col, ms=7)
        for th, dim in hazards.get(rid, []):
            ax.axvline(th / 60.0, color=HAZARD_COLOR.get(dim, "#444"), ls="--", lw=1, alpha=0.8)
    if not fill:
        _empty(ax, "no context data")
    else:
        ax.legend(fontsize=7, frameon=False, loc="upper left")
    ax.set_ylim(bottom=0)
    ax.set_xlabel("run time (min)", fontsize=9)
    ax.set_ylabel("context fill (max in interval)", fontsize=9)
    ax.set_title("Context fill vs runtime (triangles: compactions; dashed: hazards)", fontsize=10,
                 loc="left", color=INK)
    fig.tight_layout()
    return _save(fig, out)



# ---- degradation figures (analysis.degradation) --------------------------------------------------
PASS_C, FAIL_C, SKIP_C = "#009E73", "#D55E00", "#d9d9d9"
STAGE_C = "#0072B2"


def _stage_x(points, t_d: float) -> float:
    """Heatmap x position (between columns) of a stage delivery at ``t_d``."""
    for p in points:
        if p.t_s >= t_d:
            return p.idx - 0.5
    return len(points) - 0.5


def outcome_heatmap(m: Matrix, flips: list[Flip], out: Path, *, stages: list[tuple[int, float]] = (),
                 title: str = "") -> Path:
    """Tests (rows, grouped by tier) x scoring points (columns); regressions outlined in black."""
    n_t, n_p = len(m.tests), len(m.points)
    fig = Figure(figsize=(10.0, min(14.0, max(3.2, 1.6 + 0.16 * n_t))))
    ax = fig.add_subplot(111)
    if not n_t:
        _empty(ax, "no per-commit data")
        return _save(fig, out)
    code = np.full((n_t, n_p), np.nan)
    for i, tid in enumerate(m.tests):
        for j, o in enumerate(m.outcome[tid]):
            if o is not None:
                code[i, j] = 1 if o == "passed" else 0 if o in FAILING else 2
    ax.imshow(np.ma.masked_invalid(code), aspect="auto", interpolation="nearest", vmin=0, vmax=2,
              cmap=ListedColormap([FAIL_C, PASS_C, SKIP_C]))
    row = {t: i for i, t in enumerate(m.tests)}
    for f in flips:
        if f.kind == "regression" and f.test_id in row:
            for p in m.points:
                if p.t_s == f.t_s:
                    ax.add_patch(Rectangle((p.idx - 0.5, row[f.test_id] - 0.5), 1, 1, fill=False,
                                           ec=INK, lw=1.4))
                    break
    prev = None
    for i, tid in enumerate(m.tests):
        if prev is not None and m.tier[tid] != prev:
            ax.axhline(i - 0.5, color="white", lw=2.5)
        prev = m.tier[tid]
    for sid, t_d in stages:
        if sid > 0:
            x = _stage_x(m.points, t_d)
            ax.axvline(x, color=STAGE_C, ls="--", lw=1.2)
            ax.text(x + 0.1, -0.7, f"stage {sid}", fontsize=7, color=STAGE_C, va="bottom")
    ax.set_xticks(range(n_p))
    ax.set_xticklabels([f"{p.t_s / 60:.0f}" + ("" if p.point == "commit" else "*") for p in m.points],
                       fontsize=6, rotation=90)
    if n_t <= 70:
        ax.set_yticks(range(n_t))
        ax.set_yticklabels([f"t{m.tier[t]}  {t.split('::')[-1][:38]}" for t in m.tests], fontsize=6)
    else:
        ax.set_yticks([])
    ax.set_xlabel("run time (min) of each scored commit; * = checkpoint working tree", fontsize=8)
    ax.set_title(title or "Test outcomes over time (green pass, orange fail, grey skipped; black box = regression)",
                 fontsize=10, loc="left", color=INK)
    for side in ax.spines.values():
        side.set_visible(False)
    fig.tight_layout()
    return _save(fig, out)


def tier_rate_chart(rates: list[RatePoint], out: Path, *, stages: list[tuple[int, float]] = (),
                    compactions: list[float] = (), title: str = "") -> Path:
    """Per-tier pass rate, overall rate and established-test pass rate vs run time."""
    fig = Figure(figsize=(9.0, 4.2))
    ax = fig.add_subplot(111)
    _style(ax)
    if not rates:
        _empty(ax, "no per-commit data")
        return _save(fig, out)
    x = np.array([r.t_s for r in rates]) / 60.0
    tiers = sorted({t for r in rates for t in r.tiers}, key=lambda t: (not t.isdigit(), int(t) if t.isdigit() else 0, t))
    for i, t in enumerate(tiers):
        y = [r.tiers[t][0] / r.tiers[t][1] if t in r.tiers and r.tiers[t][1] else np.nan for r in rates]
        ax.plot(x, y, color=PALETTE[i % len(PALETTE)], lw=1.4, marker="o", ms=2.5, label=f"tier {t}")
    ax.plot(x, [r.overall if r.overall is not None else np.nan for r in rates], color="#888", lw=1.4, ls="--",
            label="all tests")
    ax.plot(x, [r.established if r.established is not None else np.nan for r in rates], color=INK, lw=2.6,
            marker="s", ms=3.5, label="established tests (passed before)")
    for sid, t_d in stages:
        if sid > 0:
            ax.axvline(t_d / 60.0, color=STAGE_C, ls="--", lw=1.1)
            ax.text(t_d / 60.0, 1.04, f"stage {sid}", fontsize=7, color=STAGE_C, ha="left")
    for tc in compactions:
        ax.plot([tc / 60.0], [0.02], "^", color="#CC79A7", ms=8)
    ax.set_ylim(-0.03, 1.1)
    ax.set_xlabel("run time (min)", fontsize=9)
    ax.set_ylabel("pass rate of active hidden tests", fontsize=9)
    ax.set_title(title or "Pass rate per tier and established-test pass rate (triangles: compactions)",
                 fontsize=10, loc="left", color=INK)
    ax.legend(fontsize=7, frameon=False, loc="lower left", ncol=2)
    fig.tight_layout()
    return _save(fig, out)


def regression_fill_chart(intervals: list[dict], flips: list[Flip], out: Path, *, title: str = "") -> Path:
    """Regressions per checkpoint interval (bars) and event ticks vs context fill (line)."""
    fig = Figure(figsize=(9.0, 3.8))
    ax = fig.add_subplot(111)
    _style(ax)
    if not intervals:
        _empty(ax, "no per-commit data")
        return _save(fig, out)
    for iv in intervals:
        w = (iv["t1"] - iv["t0"]) / 60.0
        ax.bar(iv["t0"] / 60.0 + w / 2, iv["regressions"], width=w * 0.9, color=FAIL_C, alpha=0.55)
        if iv["compactions"]:
            ax.plot([iv["t1"] / 60.0], [0], "^", color="#CC79A7", ms=8, clip_on=False)
    reg = [f.t_s / 60.0 for f in flips if f.kind == "regression"]
    ax.plot(reg, [-0.15] * len(reg), "|", color=INK, ms=9, clip_on=False)
    ax.set_ylabel("regressions in interval", fontsize=9, color=FAIL_C)
    ax.set_xlabel("run time (min); ticks = individual regressions, triangles = compactions", fontsize=9)
    ax2 = ax.twinx()
    fx = [(iv["t1"] / 60.0, iv["fill"]) for iv in intervals if iv["fill"] is not None]
    if fx:
        ax2.plot(*zip(*fx, strict=True), color=PALETTE[0], lw=2, marker="o", ms=3.5)
    ax2.set_ylim(0, 1.05)
    ax2.set_ylabel("context fill (max in interval)", fontsize=9, color=PALETTE[0])
    ax2.tick_params(labelsize=8)
    ax2.spines["top"].set_visible(False)
    ax2.grid(False)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=-0.3)
    ax.set_title(title or "Regression events vs context fill", fontsize=10, loc="left", color=INK)
    fig.tight_layout()
    return _save(fig, out)


def belief_gap_chart(rows: list[dict], out: Path, *, title: str = "") -> Path:
    """Failures the agent reported vs established hidden tests failing at the nearest preceding commit."""
    fig = Figure(figsize=(9.0, 3.8))
    ax = fig.add_subplot(111)
    _style(ax)
    if not rows:
        _empty(ax, "no agent test runs matched to scored commits")
        return _save(fig, out)
    x = np.array([r["t_s"] for r in rows]) / 60.0
    ax.plot(x, [r["agent_failed"] for r in rows], color=PALETTE[0], lw=1.6, marker="o", ms=4,
            label="failures the agent saw")
    ax.plot(x, [r["established_failing"] for r in rows], color=FAIL_C, lw=1.6, marker="s", ms=4,
            label="established hidden tests failing (preceding commit)")
    for r in rows:
        if r["gap"]:
            ax.axvspan(r["t_s"] / 60.0 - 0.4, r["t_s"] / 60.0 + 0.4, color=FAIL_C, alpha=0.18, lw=0)
    n_gap = sum(r["gap"] for r in rows)
    n_green = sum(r["agent_green"] for r in rows)
    ax.text(0.99, 0.97, f"agent saw all green while established tests failed: {n_gap} of {n_green} green runs",
            transform=ax.transAxes, ha="right", va="top", fontsize=8, color=INK)
    ax.set_ylim(bottom=-0.3)
    ax.set_xlabel("run time (min) of the agent's own test run", fontsize=9)
    ax.set_ylabel("failing tests", fontsize=9)
    ax.set_title(title or "Belief gap: what the agent saw vs what the hidden suite said (shaded: gap)",
                 fontsize=10, loc="left", color=INK)
    ax.legend(fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(0, 0.92))
    fig.tight_layout()
    return _save(fig, out)


# ---- behaviour and security (analysis.behavior, plan B5b) ----------------------------------------
MODES = ("RH", "GM", "AF", "CE", "ED", "CP", "CF", "OK", "DC", "SE", "UA", "VI")
MARKER_STYLE = {"stage": ("#0072B2", "-"), "directive": ("#CC79A7", "--"), "env": ("#E69F00", ":")}


def behavior_timeline(tl: dict, out: Path, *, title: str = "") -> Path:
    """One row per mode. Filled markers: hazards; hollow: tracked signals; diamonds: judge findings.
    Vertical lines: stage deliveries (solid), directives (dashed), environment changes (dotted)."""
    fig = Figure(figsize=(9.0, 4.2))
    ax = fig.add_subplot(111)
    _style(ax)
    y = {m: i for i, m in enumerate(MODES)}
    for mk in tl.get("markers", []):
        col, ls = MARKER_STYLE.get(mk["kind"], ("#888", "-"))
        ax.axvline(mk["t_s"] / 60.0, color=col, ls=ls, lw=0.9, alpha=0.7)
    for e in tl.get("events", []):
        if e["mode"] not in y:
            continue
        hz = e["severity"] == "hazard"
        judged = not e["deterministic"]
        ax.plot([e["t_s"] / 60.0], [y[e["mode"]]], "D" if judged else "o", ms=7 if hz else 5,
                mfc=(HAZARD_COLOR["safety"] if hz else "none"), mec=(HAZARD_COLOR["safety"] if hz else INK), mew=1.1)
    ax.set_yticks(range(len(MODES)))
    ax.set_yticklabels(MODES, fontsize=8)
    ax.set_ylim(-0.6, len(MODES) - 0.4)
    ax.invert_yaxis()
    dur = tl.get("duration_s")
    ax.set_xlim(0, (dur / 60.0) if dur else None)
    if not tl.get("events"):
        ax.text(0.5, 0.5, "no behaviour events", ha="center", va="center", transform=ax.transAxes, color="#777")
    ax.set_xlabel("run time (min)", fontsize=9)
    ax.set_title(title or "Behaviour timeline (filled: hazard; hollow: signal; diamond: judge; lines: stage, "
                 "directive, env change)", fontsize=9, loc="left", color=INK)
    fig.tight_layout()
    return _save(fig, out)


def security_trend_chart(rows: list[dict], out: Path, *, title: str = "") -> Path:
    """Stacked bars: new SAST findings by severity per checkpoint; line: failed exploit tests;
    crosses: AI-review High/Critical findings."""
    fig = Figure(figsize=(7.0, 3.6))
    ax = fig.add_subplot(111)
    _style(ax)
    scored = [r for r in rows if r["new_high"] is not None or r["exploits_failed"] is not None]
    if not scored:
        _empty(ax, "no security scoring")
    else:
        x = np.arange(len(rows))
        bottom = np.zeros(len(rows))
        for key, col, label in (("new_high", "#b00020", "new high"), ("new_medium", "#E69F00", "new medium"),
                                ("new_low", FAINT, "new low")):
            v = np.array([r[key] or 0 for r in rows], dtype=float)
            ax.bar(x, v, bottom=bottom, color=col, width=0.6, label=label)
            bottom += v
        ex = [r["exploits_failed"] for r in rows]
        if any(v is not None for v in ex):
            ax.plot(x, [np.nan if v is None else v for v in ex], color=INK, marker="o", ms=4, lw=1.5,
                    label="failed exploit tests")
        ai = [(i, r["ai_findings"]) for i, r in enumerate(rows) if r["ai_findings"]]
        if ai:
            ax.plot([i for i, _ in ai], [v for _, v in ai], "x", color="#0072B2", ms=8, mew=2, label="AI review findings")
        ax.set_xticks(x)
        ax.set_xticklabels([f"t{r['k']}" for r in rows], fontsize=8)
        ax.legend(fontsize=7, frameon=False, loc="upper left")
    ax.set_xlabel("checkpoint", fontsize=9)
    ax.set_ylabel("count", fontsize=9)
    ax.set_title(title or "Security trend", fontsize=10, loc="left", color=INK)
    fig.tight_layout()
    return _save(fig, out)
