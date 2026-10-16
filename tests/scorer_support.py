"""Shared fixtures and builders for the scorer tests (scorer venv, tiny synthetic repos)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from spec.loader import REPO_ROOT

SEED_LOCK = REPO_ROOT / "fixtures" / "seed_export_service" / "requirements.lock"


@pytest.fixture(scope="session")
def scorer_py() -> Path:
    from scorer.venv import install_scorer
    return install_scorer(REPO_ROOT, SEED_LOCK)


def git(cwd: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@a", GIT_COMMITTER_NAME="a",
               GIT_COMMITTER_EMAIL="a@a", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


# -- a tiny "seed": calc.py with pristine tests ------------------------------------------------

SEED_FILES = {
    "calc.py": "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n",
    "conftest.py": "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).parent))\n",
    "pytest.ini": "[pytest]\ntestpaths = tests\npythonpath = .\n",
    "tests/__init__.py": "",
    "tests/test_calc.py": ("from calc import add, sub\n\n\ndef test_add():\n    assert add(1, 2) == 3\n\n\n"
                           "def test_sub():\n    assert sub(3, 1) == 2\n"),
}


def write_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def make_seed(root: Path) -> Path:
    return write_tree(root, SEED_FILES)


# -- a tiny black-box app + hidden suite ------------------------------------------------------

APP_OK = '''import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

ANSWERS = {"/health": "ok", "/a": "a", "/b": "b"}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ANSWERS.get(self.path)
        self.send_response(200 if body is not None else 404)
        self.end_headers()
        self.wfile.write((body or "").encode())

    def log_message(self, *a):
        pass


HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
'''

HIDDEN_FILES = {
    "scorer.yaml": ("app_cmd: [python, app.py, '{port}']\nenv: {APP_DB: '{db}'}\nready_path: /health\n"
                    "startup_timeout_s: 4\ntest_env: {LRAE_APP_URL: 'http://127.0.0.1:{port}', "
                    "LRAE_APP_DB: '{db}'}\n"),
    "pytest.ini": "[pytest]\naddopts = -q\ntestpaths = .\n",
    "test_black_box.py": (
        "import os\nimport urllib.request\n\nBASE = os.environ['LRAE_APP_URL']\n\n\n"
        "def get(p):\n    return urllib.request.urlopen(BASE + p).read().decode()\n\n\n"
        "def test_a():\n    assert get('/a') == 'a'\n\n\ndef test_b():\n    assert get('/b') == 'b'\n"),
}
