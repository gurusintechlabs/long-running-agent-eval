"""Ladder task L2 (minidb): the scorer flags minidb_known_bad and passes minidb_known_good."""
import pytest

from scorer.run_checkpoint import CORE
from scorer.standalone import score_snapshot_dir
from scorer.venv import install_scorer
from spec.loader import REPO_ROOT, load_spec

pytestmark = pytest.mark.local


@pytest.fixture(scope="module")
def spec():
    loaded = load_spec(REPO_ROOT / "spec/examples/minidb.yaml")
    loaded.spec.scoring.judge_runtime = "scripted"  # never spend: the deterministic FakeJudge
    return loaded


@pytest.fixture(scope="module")
def py(spec):
    return install_scorer(REPO_ROOT, REPO_ROOT / spec.spec.task.seed_requirements_lock)


def _score(name, spec, py, tmp_path_factory):
    out = tmp_path_factory.mktemp(name) / "art"
    return score_snapshot_dir(f"fixtures/snapshots/{name}", spec, out, scorer_python=py)


def test_known_good(spec, py, tmp_path_factory):
    s = _score("minidb_known_good", spec, py, tmp_path_factory)
    vals = {n: s.metrics[n]["value"] for n in CORE}
    assert vals["P"] == 1.0 and vals["R"] == 0 and vals["C"] == 0, vals
    assert s.metrics["P"]["detail"]["total"] == 96
    assert s.hazards == []


def test_known_bad(spec, py, tmp_path_factory):
    s = _score("minidb_known_bad", spec, py, tmp_path_factory)
    probes = s.metrics["C"]["detail"]["probes"]
    assert {k for k, v in probes.items() if v["violated"]} == {"protocol-untouched", "no-embedded-db"}
    assert s.metrics["R"]["value"] == 1
    assert {h["dimension"] for h in s.hazards} == {"quality", "context"}
    assert all(n in s.metrics for n in CORE)
