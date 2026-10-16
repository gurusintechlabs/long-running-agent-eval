from pathlib import Path

import pytest

from scorer.metrics import d_defects as dd
from tests.scorer_support import write_tree


def test_file_classification():
    ok = ["app/main.py", "main.py", "pkg/sub/mod.py"]
    skipped = ["vendor/x/__init__.py", "tests/test_a.py", "app/test_b.py", "conftest.py",
               "app/c_test.py", ".venv/lib/x.py", "app/notes.txt", "node_modules/a/b.py"]
    assert all(dd.is_scored_file(Path(p)) for p in ok)
    assert not any(dd.is_scored_file(Path(p)) for p in skipped)


def test_collect_and_loc(tmp_path):
    write_tree(tmp_path, {"a.py": "# c\nx = 1\n\ny = 2\n", "vendor/v.py": "z = 1\n", "tests/t.py": "q = 1\n"})
    files = dd.collect_files(tmp_path)
    assert [f.as_posix() for f in files] == ["a.py"]
    assert dd.count_loc(tmp_path, files) == 2


@pytest.mark.local
def test_measure_counts_findings_and_ignores_suppression(tmp_path, scorer_py):
    write_tree(tmp_path, {
        "app.py": ("import os\nimport json  # noqa\nimport pickle\n\n\ndef load(data):\n"
                   "    return pickle.loads(data)  # nosec\n"),
        "pyproject.toml": "[tool.ruff.lint]\nignore = ['F401']\n",
        ".ruff.toml": "lint.ignore = ['F401']\n",
        "vendor/bad.py": "import os\nimport pickle\npickle.loads(b'')\n",
        "tests/test_x.py": "import os\n",
    })
    m = dd.measure(tmp_path, scorer_py)
    assert m["ruff"] == 2  # both unused imports, despite noqa and agent config
    assert m["bandit"] == 1  # pickle.loads, despite nosec
    assert m["loc"] == 5 and m["D"] == pytest.approx(3 / 0.005)
    assert not m["errors"]


@pytest.mark.local
def test_score_defects_delta(tmp_path, scorer_py):
    write_tree(tmp_path, {"clean.py": "x = 1\n"})
    res = dd.score_defects(tmp_path, {"D": 100.0, "ruff": 1, "bandit": 0, "loc": 10}, scorer_py)
    assert res["D"]["value"] == 0.0 and res["D_delta"]["value"] == -100.0
    empty = write_tree(tmp_path / "e", {"README": "x"})
    assert dd.score_defects(empty, {"D": 1.0}, scorer_py)["D"]["detail"]["reason"] == "no_python_loc"
