"""Black-box runner for the minidb acceptance tests. Never imports minidb.

Environment (set by the scorer):
  LRAE_WORKSPACE  absolute path of a temp copy of the repo under test (cwd of every run)
  LRAE_PYTHON     interpreter used to run ``python -m minidb`` (default: this interpreter)

Every ``run`` starts a fresh ``python -m minidb`` process (a fresh, empty database), feeds it the
script on stdin and parses one JSON line per statement. Comparisons of values are type-strict
(``1`` != ``1.0`` != ``True``), because the wire types are part of the contract.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

RUN_TIMEOUT_S = 10


class Result:
    def __init__(self, raw: dict, stmt: str) -> None:
        self.raw, self.stmt = raw, stmt

    @property
    def ok(self) -> bool:
        return self.raw.get("ok") is True

    @property
    def error_type(self) -> str | None:
        err = self.raw.get("error")
        return err.get("type") if isinstance(err, dict) else None

    @property
    def columns(self) -> list:
        assert self.ok and "columns" in self.raw, f"{self.stmt!r} gave {self.raw}"
        return self.raw["columns"]

    @property
    def rows(self) -> list:
        assert self.ok and "rows" in self.raw, f"{self.stmt!r} gave {self.raw}"
        return self.raw["rows"]

    @property
    def rowcount(self) -> int:
        assert self.ok and "rowcount" in self.raw, f"{self.stmt!r} gave {self.raw}"
        return self.raw["rowcount"]

    def __repr__(self) -> str:
        return f"Result({self.stmt!r} -> {self.raw})"


def split(script: str) -> list[str]:
    """Statements of ``script`` as the protocol splits them (quotes, '' escapes, -- comments)."""
    out, buf, i, n = [], [], 0, len(script)
    while i < n:
        ch = script[i]
        if ch == "'":
            j = i + 1
            while j < n:
                if script[j] == "'":
                    if j + 1 < n and script[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            buf.append(script[i:j + 1])
            i = j + 1
        elif ch == "-" and script.startswith("--", i):
            j = script.find("\n", i)
            i = n if j < 0 else j
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    stmt = "".join(buf).strip()
    if stmt:
        out.append(stmt)
    return out


def _workspace() -> Path:
    ws = os.environ.get("LRAE_WORKSPACE")
    if not ws:
        raise RuntimeError("LRAE_WORKSPACE is not set")
    return Path(ws)


def run(script: str, *, cwd: Path | None = None) -> list[Result]:
    """Run ``script`` in a fresh minidb process; one Result per statement."""
    stmts = split(script)
    python = os.environ.get("LRAE_PYTHON") or sys.executable
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    proc = subprocess.run([python, "-m", "minidb"], input=script, cwd=cwd or _workspace(),
                          env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=RUN_TIMEOUT_S)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == len(stmts), (
        f"expected {len(stmts)} output lines, got {len(lines)} (exit {proc.returncode}); "
        f"stderr tail: {proc.stderr[-800:]!r}; stdout tail: {proc.stdout[-400:]!r}")
    results = []
    for line, stmt in zip(lines, stmts):
        try:
            raw = json.loads(line)
        except ValueError:
            raise AssertionError(f"{stmt!r}: output is not JSON: {line[:200]!r}") from None
        assert isinstance(raw, dict) and isinstance(raw.get("ok"), bool), f"{stmt!r}: {raw}"
        results.append(Result(raw, stmt))
    return results


def run_ok(script: str, **kw) -> list[Result]:
    """Like ``run`` but every statement must succeed."""
    res = run(script, **kw)
    for r in res:
        assert r.ok, f"statement failed: {r}"
    return res


def query(setup: str, sql: str, **kw) -> Result:
    """Run ``setup`` (all statements must succeed), then ``sql``; return the last result."""
    res = run(setup + "\n" + sql, **kw)
    for r in res[:-1]:
        assert r.ok, f"setup statement failed: {r}"
    return res[-1]


def tag(v: Any) -> Any:
    """Type-strict comparison key for wire values."""
    if isinstance(v, list):
        return [tag(x) for x in v]
    if isinstance(v, float):
        return ("float", round(v, 9))
    return (type(v).__name__, v)


def assert_rows(result: Result, expected: list[list], *, columns: list[str] | None = None) -> None:
    assert result.ok, f"query failed: {result}"
    if columns is not None:
        assert result.columns == columns, f"{result.stmt!r}: columns {result.columns}"
    assert tag(result.rows) == tag(expected), (
        f"{result.stmt!r}:\n  got      {result.rows}\n  expected {expected}")


def assert_error(result: Result, type_name: str) -> None:
    assert not result.ok, f"expected {type_name}, got success: {result}"
    assert result.error_type == type_name, f"expected {type_name}: {result}"


def lit(text: str) -> str:
    """A SQL string literal for ``text``."""
    return "'" + str(text).replace("'", "''") + "'"


def value(result: Result) -> Any:
    """The single value of a one-row, one-column query."""
    assert result.ok and len(result.rows) == 1 and len(result.rows[0]) == 1, f"{result}"
    return result.rows[0][0]


# A small schema without constraints, used from tier 2 on.
PEOPLE = """
CREATE TABLE people (id INTEGER, name TEXT, age INTEGER, city TEXT, score REAL);
INSERT INTO people VALUES
  (1, 'Ann', 34, 'Oslo', 7.5),
  (2, 'bob', 27, 'Rome', NULL),
  (3, 'Cid', NULL, 'Oslo', 9.0),
  (4, 'Dee', 45, NULL, 6.25),
  (5, 'Eve', 27, 'Lima', 8.0),
  (6, 'Fay', 31, 'Rome', 7.5);
"""

# Employees and departments with keys and constraints, used from tier 6 on.
COMPANY = """
CREATE TABLE dept (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, budget REAL);
CREATE TABLE emp (id INTEGER PRIMARY KEY, name TEXT NOT NULL, dept_id INTEGER,
                  salary INTEGER, manager_id INTEGER, active BOOLEAN DEFAULT TRUE);
INSERT INTO dept VALUES (1, 'eng', 1000.0), (2, 'ops', 500.0), (3, 'sales', NULL), (4, 'legal', 200.0);
INSERT INTO emp (id, name, dept_id, salary, manager_id) VALUES
  (1, 'ada', 1, 300, NULL),
  (2, 'bo', 1, 200, 1),
  (3, 'cy', 2, 150, 1),
  (4, 'di', 2, 150, 3),
  (5, 'ed', 3, NULL, 1),
  (6, 'flo', NULL, 100, 2),
  (7, 'gus', 1, 250, 1);
UPDATE emp SET active = FALSE WHERE id = 4;
"""
