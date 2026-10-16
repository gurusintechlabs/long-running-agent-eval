import pytest

from scorer import sandbox
from scorer.metrics import p_hidden
from tests.scorer_support import APP_OK, HIDDEN_FILES, write_tree


def test_placeholder_substitution(tmp_path):
    assert p_hidden._fmt("http://x:{port}/{db}", 81, tmp_path / "d.db") == f"http://x:81/{tmp_path}/d.db"


def test_load_config_requires_keys(tmp_path):
    (tmp_path / "scorer.yaml").write_text("app_cmd: [x]\n")
    with pytest.raises(ValueError):
        p_hidden.load_config(tmp_path)


def test_load_config_without_app_is_allowed(tmp_path):
    (tmp_path / "scorer.yaml").write_text("test_env: {LRAE_WORKSPACE: '{ws}'}\n")
    assert "app_cmd" not in p_hidden.load_config(tmp_path)


SERVERLESS_HIDDEN = {
    "scorer.yaml": "test_env: {LRAE_WORKSPACE: '{ws}', LRAE_PYTHON: '{python}'}\n",
    "pytest.ini": "[pytest]\ntestpaths = .\n",
    "test_cli.py": (
        "import os, subprocess\n"
        "def run(text):\n"
        "    return subprocess.run([os.environ['LRAE_PYTHON'], '-m', 'echoer'], input=text,\n"
        "                          cwd=os.environ['LRAE_WORKSPACE'], capture_output=True, text=True,\n"
        "                          timeout=10).stdout\n"
        "def test_echo():\n    assert run('hi') == 'HI'\n"
        "def test_empty():\n    assert run('') == ''\n"),
}


@pytest.mark.local
def test_serverless_task_runs_program_from_the_temp_copy(tmp_path, scorer_py):
    hidden = write_tree(tmp_path / "hidden", SERVERLESS_HIDDEN)
    ws = write_tree(tmp_path / "ws", {"echoer/__init__.py": "",
                                      "echoer/__main__.py": "import sys\nsys.stdout.write(sys.stdin.read().upper())\n"})
    res = p_hidden.score_hidden(ws, hidden, scorer_py)
    assert res["value"] == 1.0, res["detail"]
    assert res["detail"]["app_cmd"] is None
    broken = write_tree(tmp_path / "ws2", {"echoer/__init__.py": "", "echoer/__main__.py": "raise SystemExit(3)\n"})
    assert p_hidden.score_hidden(broken, hidden, scorer_py)["value"] == 0.5
    assert not sandbox.leftover_processes() and not sandbox.leftover_temp_dirs()


@pytest.mark.local
def test_all_pass(tmp_path, scorer_py):
    hidden = write_tree(tmp_path / "hidden", HIDDEN_FILES)
    app = write_tree(tmp_path / "app", {"app.py": APP_OK})
    res = p_hidden.score_hidden(app, hidden, scorer_py)
    assert res["value"] == 1.0
    assert res["detail"]["total"] == 2 and set(res["detail"]["outcomes"].values()) == {"passed"}
    assert not sandbox.leftover_processes() and not sandbox.leftover_temp_dirs()


@pytest.mark.local
def test_partial_pass(tmp_path, scorer_py):
    hidden = write_tree(tmp_path / "hidden", HIDDEN_FILES)
    app = write_tree(tmp_path / "app", {"app.py": APP_OK.replace('"/b": "b"', '"/b": "WRONG"')})
    res = p_hidden.score_hidden(app, hidden, scorer_py)
    assert res["value"] == 0.5
    assert res["detail"]["outcomes"]["test_black_box.py::test_b"] == "failed"
    assert res["detail"]["outcomes"]["test_black_box.py::test_a"] == "passed"


@pytest.mark.local
def test_app_that_cannot_start_scores_zero_with_reason(tmp_path, scorer_py):
    hidden = write_tree(tmp_path / "hidden", HIDDEN_FILES)
    app = write_tree(tmp_path / "app", {"app.py": "import definitely_not_installed_pkg\n"})
    res = p_hidden.score_hidden(app, hidden, scorer_py)
    assert res["value"] == 0.0
    assert res["detail"]["reason"].startswith("app_start_failed")
    assert "definitely_not_installed_pkg" in res["detail"]["app_log_tail"]
    assert res["detail"]["total"] == 2
    assert set(res["detail"]["outcomes"].values()) == {"failed"}
