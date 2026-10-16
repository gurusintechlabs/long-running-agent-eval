"""Deterministic matplotlib charts (Agg, fixed sizes, no dates in PNG metadata).

Every function takes plain data (see ``report.dashboard`` for how it is gathered from SQLite),
writes one PNG and returns its path. Time axes are in minutes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from analysis.survival import KM
from analysis.trends import CORE_METRICS, Series, median_by_k

# Okabe-Ito: colour-blind safe, distinct in light and print.
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#7a7a7a"]
HAZARD_COLOR = {"quality": "#D55E00", "context": "#CC79A7", "cost": "#E69F00", "safety": "#b00020"}
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

