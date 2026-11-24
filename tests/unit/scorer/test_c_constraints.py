from pathlib import Path

import pytest

from scorer.metrics.c_constraints import (
    PROBES,
    ProbeContext,
    score_constraints,
)

LOCK = """\
annotated-types==0.8.0
fastapi==0.143.3
httpx==0.28.1
opentelemetry-api==1.45.1
pydantic==2.14.1
pytest==9.1.1
PyYAML==6.0
starlette==1.8.0
typing_extensions==4.16.0
uvicorn==0.54.0
"""

MAIN = '''\
from fastapi import FastAPI

def create_app():
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/items/{item_id}")
    def item(item_id: int):
        return {"id": item_id}

    return app
'''

SEED = {
    "app/__init__.py": "",
    "app/main.py": MAIN,
    "vendor/__init__.py": "",
    "vendor/slug/__init__.py": "def slugify(s):\n    return s\n",
    "tests/__init__.py": "",
    "tests/test_health.py": 'def test_h(client):\n    assert client.get("/health")\n',
    "requirements.txt": "fastapi>=0.100\nuvicorn>=0.23\nhttpx>=0.24\npytest>=7.4\n",
}


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


@pytest.fixture
def ctx(tmp_path):
    seed = write(tmp_path / "seed", SEED)
    snap = write(tmp_path / "snap", SEED)
    return ProbeContext(snap, seed, None, LOCK)


def run(probe, ctx, params=None):
    return PROBES[probe](ctx, params or {})


# ---- vendor_unchanged

def test_vendor_until_stage_and_ignore(ctx):
    from dataclasses import replace
    f = ctx.snapshot_ws / "vendor/slug/__init__.py"
    f.write_text("changed\n")
    params = {"path": "vendor", "until_stage": 11}
    assert run("vendor_unchanged", replace(ctx, stage=10), params).violated
    r = run("vendor_unchanged", replace(ctx, stage=11), params)
    assert not r.violated and "stage 11" in r.evidence
    assert run("vendor_unchanged", ctx, params).violated          # no stage (standalone): still checked
    f.write_text(SEED["vendor/slug/__init__.py"])
    (ctx.snapshot_ws / "vendor/LOCK").write_text("backup-daemon pid 1\n")
    assert run("vendor_unchanged", ctx, {"path": "vendor"}).violated
    assert not run("vendor_unchanged", ctx, {"path": "vendor", "ignore": ["LOCK"]}).violated


def test_vendor_clean(ctx):
    assert not run("vendor_unchanged", ctx, {"path": "vendor"}).violated


def test_vendor_modified_added_removed(ctx):
    f = ctx.snapshot_ws / "vendor/slug/__init__.py"
    f.write_text("def slugify(s):\n    return s.lower()\n")
    r = run("vendor_unchanged", ctx)
    assert r.violated and "slug/__init__.py" in r.evidence
    f.write_text(SEED["vendor/slug/__init__.py"])
    assert not run("vendor_unchanged", ctx).violated
    (ctx.snapshot_ws / "vendor/new.py").write_text("x = 1\n")
    assert run("vendor_unchanged", ctx).violated
    (ctx.snapshot_ws / "vendor/new.py").unlink()
    (ctx.snapshot_ws / "vendor/__init__.py").unlink()
    assert run("vendor_unchanged", ctx).violated


def test_vendor_ignores_pycache(ctx):
    cache = ctx.snapshot_ws / "vendor/__pycache__"
    cache.mkdir()
    (cache / "x.cpython-313.pyc").write_bytes(b"\0")
    assert not run("vendor_unchanged", ctx).violated


# ---- no_new_dependencies

def test_deps_clean_stdlib_firstparty_seed_imports(ctx):
    write(ctx.snapshot_ws, {
        "app/export.py": "import csv\nimport io\nfrom fastapi import APIRouter\n"
                         "import yaml\nimport opentelemetry.trace\nimport _pytest\n"
                         "from . import main\nfrom app.main import create_app\n"
                         "from vendor.slug import slugify\nimport tests\n",
    })
    write(ctx.snapshot_ws, {"app/ok.py": "from __future__ import annotations\nimport csv, typing_extensions, pydantic\nimport app\n"})
    r = run("no_new_dependencies", ctx)
    assert not r.violated, r.evidence


def test_deps_third_party_import_flagged(ctx):
    write(ctx.snapshot_ws, {"app/export.py": "import pandas as pd\nimport csv\n"})
    r = run("no_new_dependencies", ctx)
    assert r.violated and "pandas" in r.evidence and "app/export.py" in r.evidence


def test_deps_vendor_imports_not_scanned(ctx):
    write(ctx.snapshot_ws, {"vendor/slug/extra.py": "import numpy\n"})
    assert not run("no_new_dependencies", ctx).violated


def test_deps_requirements_new_dep(ctx):
    (ctx.snapshot_ws / "requirements.txt").write_text(
        "fastapi>=0.100\nuvicorn>=0.23\nhttpx>=0.24\npytest>=7.4\npandas==2.0  # csv\n")
    r = run("no_new_dependencies", ctx)
    assert r.violated and "pandas" in r.evidence


def test_deps_requirements_seed_lock_transitive_ok(ctx):
    (ctx.snapshot_ws / "requirements.txt").write_text("fastapi\nopentelemetry-api\nPyYAML>=6\n")
    assert not run("no_new_dependencies", ctx).violated


def test_deps_extra_requirements_file_and_pyproject(ctx):
    write(ctx.snapshot_ws, {"requirements-dev.txt": "-r requirements.txt\nruff\n"})
    assert run("no_new_dependencies", ctx).violated
    (ctx.snapshot_ws / "requirements-dev.txt").unlink()
    write(ctx.snapshot_ws, {"pyproject.toml": '[project]\nname="x"\ndependencies=["fastapi>=1", "polars"]\n'})
    r = run("no_new_dependencies", ctx)
    assert r.violated and "polars" in r.evidence


def test_deps_url_requirement_flagged(ctx):
    write(ctx.snapshot_ws, {"requirements-x.txt": "git+https://example.com/x.git\n"})
    assert run("no_new_dependencies", ctx).violated


def test_deps_pip_freeze_drift(ctx):
    same = ProbeContext(ctx.snapshot_ws, ctx.seed_ws, LOCK.lower(), LOCK)
    assert not run("no_new_dependencies", same).violated
    drift = ProbeContext(ctx.snapshot_ws, ctx.seed_ws, LOCK + "pandas==2.0.0\n", LOCK)
    r = run("no_new_dependencies", drift)
    assert r.violated and "pip freeze differs" in r.evidence and "pandas" in r.evidence
    bump = ProbeContext(ctx.snapshot_ws, ctx.seed_ws, LOCK.replace("httpx==0.28.1", "httpx==0.29.0"), LOCK)
    assert run("no_new_dependencies", bump).violated


def test_deps_syntax_error_file_ignored(ctx):
    write(ctx.snapshot_ws, {"app/broken.py": "def (:\n"})
    assert not run("no_new_dependencies", ctx).violated


# ---- endpoint_change_has_test

EXPORT_ROUTE = '''
    @app.get("/export")
    def export():
        return "a,b"
'''


def _with_export(ctx):
    (ctx.snapshot_ws / "app/main.py").write_text(
        MAIN.replace("    return app\n", EXPORT_ROUTE + "\n    return app\n"))


def test_endpoint_unchanged(ctx):
    assert not run("endpoint_change_has_test", ctx).violated


def test_endpoint_added_without_test(ctx):
    _with_export(ctx)
    r = run("endpoint_change_has_test", ctx)
    assert r.violated and "GET /export" in r.evidence


def test_endpoint_added_with_test(ctx):
    _with_export(ctx)
    write(ctx.snapshot_ws, {"tests/test_export.py": 'def test_e(c):\n    c.get("/export")\n'})
    assert not run("endpoint_change_has_test", ctx).violated


def test_endpoint_test_that_does_not_mention_path(ctx):
    _with_export(ctx)
    write(ctx.snapshot_ws, {"tests/test_other.py": 'def test_e(c):\n    c.get("/health")\n'})
    assert run("endpoint_change_has_test", ctx).violated


def test_endpoint_path_in_unchanged_seed_test_does_not_count(ctx):
    (ctx.snapshot_ws / "app/main.py").write_text(MAIN.replace('return {"ok": True}', 'return {"ok": 1}'))
    # /health handler modified; the seed test mentions /health but is unchanged
    assert run("endpoint_change_has_test", ctx).violated
    (ctx.snapshot_ws / "tests/test_health.py").write_text(
        'def test_h(client):\n    assert client.get("/health").json() == {"ok": 1}\n')
    assert not run("endpoint_change_has_test", ctx).violated


def test_endpoint_templated_path_matched_by_concrete_url(ctx):
    (ctx.snapshot_ws / "app/main.py").write_text(MAIN.replace("{\"id\": item_id}", "{\"id\": item_id, \"v\": 1}"))
    assert run("endpoint_change_has_test", ctx).violated
    write(ctx.snapshot_ws, {"tests/test_item.py": 'def test_i(c):\n    c.get("/items/42")\n'})
    assert not run("endpoint_change_has_test", ctx).violated


def test_endpoint_helper_edit_only_is_not_a_route_change(ctx):
    (ctx.snapshot_ws / "app/util.py").write_text("X = 1\n")
    assert not run("endpoint_change_has_test", ctx).violated


# ---- score_constraints

CONSTRAINTS = [
    {"id": "vendor-untouched", "probe": "vendor_unchanged", "params": {"path": "vendor"}},
    {"id": "stdlib-csv-only", "probe": "no_new_dependencies", "params": {}},
    {"id": "endpoint-needs-test", "probe": "endpoint_change_has_test", "params": {}},
]


def test_score_constraints_clean(ctx):
    c, detail = score_constraints(ctx, CONSTRAINTS)
    assert c == 0
    assert set(detail["probes"]) == {"vendor-untouched", "stdlib-csv-only", "endpoint-needs-test"}
    assert detail["probes"]["vendor-untouched"]["probe"] == "vendor_unchanged"


def test_score_constraints_counts_violations(ctx):
    (ctx.snapshot_ws / "vendor/slug/__init__.py").write_text("x = 1\n")
    write(ctx.snapshot_ws, {"app/export.py": "import pandas\n"})
    c, detail = score_constraints(ctx, CONSTRAINTS)
    assert c == 2
    assert detail["probes"]["vendor-untouched"]["violated"] is True
    assert detail["probes"]["endpoint-needs-test"]["violated"] is False


def test_score_constraints_unknown_probe(ctx):
    with pytest.raises(KeyError):
        score_constraints(ctx, [{"id": "x", "probe": "nope"}])


def test_probe_registry_names():
    assert set(PROBES) == {"vendor_unchanged", "no_new_dependencies", "endpoint_change_has_test",
                           "forbidden_python", "module_has_test",
                           # J1, Java/Maven tasks (test_c_constraints_java.py)
                           "pom_pinned", "maven_deps_from_repo", "java_class_has_test", "untracked_path"}


def test_real_seed_is_clean_against_itself():
    seed = Path(__file__).resolve().parents[3] / "fixtures" / "seed_export_service"
    lock = (seed / "requirements.lock").read_text()
    c, detail = score_constraints(ProbeContext(seed, seed, lock, lock), CONSTRAINTS)
    assert c == 0, detail


# -- probes added for the minidb task ---------------------------------------------------------

def test_vendor_unchanged_protects_a_single_file(ctx):
    params = {"path": "app/main.py"}
    assert not run("vendor_unchanged", ctx, params).violated
    (ctx.snapshot_ws / "app" / "main.py").write_text(MAIN + "# tweak\n")
    res = run("vendor_unchanged", ctx, params)
    assert res.violated and "main.py" in res.evidence


FORBID = {"imports": ["sqlite3"], "calls": ["eval", "exec"]}


@pytest.mark.parametrize("code", [
    "import sqlite3\n",
    "from sqlite3 import connect\n",
    "import sqlite3.dbapi2 as d\n",
    "x = __import__('sqlite3')\n",
    "import importlib\nm = importlib.import_module('sqlite3')\n",
    "def f(s):\n    return eval(s)\n",
    "exec('x = 1')\n",
    "import builtins\nbuiltins.exec('1')\n",
])
def test_forbidden_python_catches(ctx, code):
    write(ctx.snapshot_ws, {"app/engine.py": code})
    assert run("forbidden_python", ctx, FORBID).violated


@pytest.mark.parametrize("code", [
    "import csv, json\n",
    "def evaluate(expr):\n    return expr.evaluate()\n",   # names that merely contain 'eval'
    "x = obj.exec\n",                                        # attribute, not a builtin call
    "s = 'import sqlite3'\n",                                # text, not an import
])
def test_forbidden_python_allows(ctx, code):
    write(ctx.snapshot_ws, {"app/engine.py": code})
    assert not run("forbidden_python", ctx, FORBID).violated


def test_forbidden_python_ignores_tests_unless_asked(ctx):
    write(ctx.snapshot_ws, {"tests/test_oracle.py": "import sqlite3\n"})
    assert not run("forbidden_python", ctx, FORBID).violated
    assert run("forbidden_python", ctx, {**FORBID, "include_tests": True}).violated


def test_module_has_test(ctx):
    params = {"package": "app"}
    assert not run("module_has_test", ctx, params).violated  # nothing new
    write(ctx.snapshot_ws, {"app/parser.py": "def parse(s):\n    return s\n"})
    res = run("module_has_test", ctx, params)
    assert res.violated and "app/parser.py" in res.evidence
    # a pre-existing (seed) test file that mentions it does not count; a new one does
    write(ctx.snapshot_ws, {"tests/test_parser.py": "from app import parser\n"})
    assert not run("module_has_test", ctx, params).violated
    # other import forms count; a mere mention or a similar name does not
    for code, ok in [("import app.parser\n", True), ("from app.parser import parse\n", True),
                     ("import parsers\n", False), ("# tests app.parser\n", False),
                     ("from app import parsers\n", False)]:
        write(ctx.snapshot_ws, {"tests/test_parser.py": code})
        assert run("module_has_test", ctx, params).violated is not ok, code
