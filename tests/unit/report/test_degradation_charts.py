from pathlib import Path

from analysis.degradation import Matrix
from report import charts

PNG = b"\x89PNG\r\n\x1a\n"


def test_charts_handle_empty_data(tmp_path):
    outs = [charts.outcome_heatmap(Matrix("r", "hidden"), [], tmp_path / "a.png"),
            charts.tier_rate_chart([], tmp_path / "b.png"),
            charts.regression_fill_chart([], [], tmp_path / "c.png"),
            charts.belief_gap_chart([], tmp_path / "d.png")]
    for o in outs:
        assert Path(o).read_bytes()[:8] == PNG
