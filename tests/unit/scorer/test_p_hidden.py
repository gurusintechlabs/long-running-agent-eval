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


def test_suite_timeout_is_configurable(tmp_path):
    (tmp_path / "scorer.yaml").write_text("suite_timeout_s: 1800\n")
    assert p_hidden.suite_timeout(p_hidden.load_config(tmp_path)) == 1800
    (tmp_path / "scorer.yaml").write_text("test_env: {}\n")
    assert p_hidden.suite_timeout(p_hidden.load_config(tmp_path)) == p_hidden.SUITE_TIMEOUT_S
    (tmp_path / "scorer.yaml").write_text("suite_timeout_s: -5\n")
    with pytest.raises(ValueError):
        p_hidden.load_config(tmp_path)


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


def test_tier_of_uses_the_file_name_number_else_the_stem():
    assert p_hidden.tier_of("test_t01_basics.py::test_x") == 1
    assert p_hidden.tier_of("test_t12_views_alter.py::TestA::test_y[param]") == 12
    assert p_hidden.tier_of("test_export_acceptance.py::test_z") == "test_export_acceptance"


def test_tier_of_requires_the_t_prefix_and_trailing_underscore():
    assert p_hidden.tier_of("sub/test_t3_x.py::t") == 3
    assert p_hidden.tier_of("test_t3.py::t") == "test_t3"
    assert p_hidden.tier_of("test_tier_x.py::t") == "test_tier_x"


STAGED_HIDDEN = {
    **HIDDEN_FILES,
    "test_t02_late.py": (
        "import os\nimport urllib.request\n\nimport pytest\n\n"
        "@pytest.mark.skipif(int(os.environ.get('LRAE_STAGE', '9')) < 1, reason='not yet')\n"
        "def test_late():\n"
        "    assert urllib.request.urlopen(os.environ['LRAE_APP_URL'] + '/late').read() == b'late'\n"),
}


@pytest.mark.local
def test_stage_skips_tests_and_excludes_them_from_the_denominator(tmp_path, scorer_py):
    hidden = write_tree(tmp_path / "hidden", STAGED_HIDDEN)
    app = write_tree(tmp_path / "app", {"app.py": APP_OK})
    s0 = p_hidden.score_hidden(app, hidden, scorer_py, stage=0)
    d = s0["detail"]
    assert s0["value"] == 1.0 and (d["total"], d["active"], d["skipped"], d["passed"]) == (3, 2, 1, 2)
    assert d["outcomes"]["test_t02_late.py::test_late"] == "skipped"
    assert d["tiers"] == {"test_black_box.py::test_a": "test_black_box",
                          "test_black_box.py::test_b": "test_black_box", "test_t02_late.py::test_late": 2}
    s1 = p_hidden.score_hidden(app, hidden, scorer_py, stage=1)   # 'late' is active and fails
    assert s1["value"] == pytest.approx(2 / 3) and s1["detail"]["skipped"] == 0
    none = p_hidden.score_hidden(app, hidden, scorer_py)           # no stage: everything active
    assert none["detail"]["active"] == 3 and none["detail"]["stage"] is None
    assert not sandbox.leftover_processes() and not sandbox.leftover_temp_dirs()


TIMING_HIDDEN = {
    "scorer.yaml": ("test_env: {LRAE_WORKSPACE: '{ws}', LRAE_PYTHON: '{python}'}\n"
                    "timing_k: 'timing'\n"),
    "pytest.ini": "[pytest]\ntestpaths = .\n",
    "test_x.py": (
        "import os, pathlib\n"
        "def test_plain():\n    assert True\n"
        "def test_timing_flaky():\n"
        "    # fails on the first attempt in this workspace, passes on the rerun\n"
        "    marker = pathlib.Path(os.environ['LRAE_WORKSPACE']) / '.attempted'\n"
        "    first = not marker.exists()\n"
        "    marker.write_text('x')\n"
        "    assert not first\n"),
}


@pytest.mark.local
def test_timing_tests_rerun_once_at_checkpoints_and_are_deselected_per_commit(tmp_path, scorer_py):
    hidden = write_tree(tmp_path / "hidden", TIMING_HIDDEN)
    ws = write_tree(tmp_path / "ws", {"a.txt": "x"})
    res = p_hidden.score_hidden(ws, hidden, scorer_py)
    assert res["value"] == 1.0, res["detail"]
    assert res["detail"]["timing_reruns"] == {"test_x.py::test_timing_flaky": "passed"}
    per_commit = p_hidden.score_hidden(ws, hidden, scorer_py, timing=False)
    assert set(per_commit["detail"]["outcomes"]) == {"test_x.py::test_plain"}
    assert per_commit["value"] == 1.0 and "timing_reruns" not in per_commit["detail"]
