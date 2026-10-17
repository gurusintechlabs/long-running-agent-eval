"""Black-box runner for the minidb v2 acceptance tests. Never imports minidb.

Environment (set by the scorer):
  LRAE_WORKSPACE  absolute path of a temp copy of the repo under test (cwd of every process)
  LRAE_PYTHON     interpreter used to run ``python -m minidb`` (default: this interpreter)
  LRAE_STAGE      the stage of the brief in force (docs/interfaces.md §9); unset = final stage

Every ``run`` starts a fresh ``python -m minidb`` process (a fresh, empty database), feeds it the
script on stdin and parses one JSON line per statement. ``Session`` keeps one process open for
interactive use: statement-by-statement answers, pipelined timing (performance tests), ``--db``
files and SIGKILL (crash tests). Comparisons of values are type-strict (``1`` != ``1.0`` !=
``True``), because the wire types are part of the contract.

Stage windows: ``@stage(introduced, retired=None)`` marks a test active for
``introduced <= LRAE_STAGE < retired``; outside its window it is skipped (not counted).
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest

RUN_TIMEOUT_S = 20
FINAL_STAGE = 6


# ------------------------------------------------------------------ stages

def current_stage() -> int:
    raw = os.environ.get("LRAE_STAGE", "").strip()
    return int(raw) if raw else FINAL_STAGE


def stage(introduced: int, retired: int | None = None):
    """Active for ``introduced <= stage < retired`` (``retired=None``: forever)."""
    if not 0 <= introduced <= FINAL_STAGE or (retired is not None and not introduced < retired
                                              <= FINAL_STAGE):
        raise ValueError(f"bad stage window [{introduced}, {retired})")
    s = current_stage()
    active = introduced <= s and (retired is None or s < retired)
    mark = pytest.mark.skipif(
        not active, reason=f"stage window [{introduced}, {retired}) inactive at stage {s}")

    def deco(fn):
        fn = mark(fn)
        fn.lrae_stage = (introduced, retired)
        return fn
    return deco


# ------------------------------------------------------------------ results

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
        return f"Result({self.stmt[:300]!r} -> {str(self.raw)[:600]})"


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


def _python() -> str:
    return os.environ.get("LRAE_PYTHON") or sys.executable


def _env() -> dict[str, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    return env


def _parse(line: str, stmt: str) -> Result:
    try:
        raw = json.loads(line)
    except ValueError:
        raise AssertionError(f"{stmt[:200]!r}: output is not JSON: {line[:200]!r}") from None
    assert isinstance(raw, dict) and isinstance(raw.get("ok"), bool), f"{stmt[:200]!r}: {raw}"
    return Result(raw, stmt)


def run(script: str, *, cwd: Path | None = None, args: tuple[str, ...] = (),
        timeout: float = RUN_TIMEOUT_S) -> list[Result]:
    """Run ``script`` in a fresh minidb process; one Result per statement."""
    stmts = split(script)
    proc = subprocess.run([_python(), "-m", "minidb", *args], input=script,
                          cwd=cwd or _workspace(), env=_env(), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == len(stmts), (
        f"expected {len(stmts)} output lines, got {len(lines)} (exit {proc.returncode}); "
        f"stderr tail: {proc.stderr[-800:]!r}; stdout tail: {proc.stdout[-400:]!r}")
    return [_parse(line, stmt) for line, stmt in zip(lines, stmts)]


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


# ------------------------------------------------------------------ long-lived process

class Session:
    """One ``python -m minidb [args]`` process, driven statement by statement.

    ``execute`` sends one statement and waits for its line; ``pipeline`` sends many back to back
    (from a writer thread) and measures the wall time until the last answer; ``kill`` sends
    SIGKILL. Use as a context manager so the process never outlives the test.
    """

    def __init__(self, *args: str, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._err = tempfile.TemporaryFile()
        self.t_start = time.perf_counter()
        self.proc = subprocess.Popen([_python(), "-m", "minidb", *args], cwd=_workspace(),
                                     env=_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self._err, text=True, encoding="utf-8",
                                     errors="replace", bufsize=1)
        self._lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        for line in self.proc.stdout:
            if line.strip():
                self._lines.put(line)
        self._lines.put(None)

    def _stderr_tail(self) -> str:
        try:
            self._err.seek(0)
            return self._err.read()[-800:].decode("utf-8", "replace")
        except (OSError, ValueError):
            return ""

    def _next(self, stmt: str, timeout: float | None = None) -> Result:
        try:
            line = self._lines.get(timeout=self.timeout if timeout is None else timeout)
        except queue.Empty:
            raise AssertionError(f"no answer within {timeout or self.timeout}s to "
                                 f"{stmt[:200]!r}; stderr: {self._stderr_tail()!r}") from None
        if line is None:
            self._lines.put(None)
            raise AssertionError(f"minidb exited before answering {stmt[:200]!r} "
                                 f"(exit {self.proc.poll()}); stderr: {self._stderr_tail()!r}")
        return _parse(line, stmt)

    def send(self, stmt: str) -> None:
        """Write one statement without waiting for its answer."""
        self.proc.stdin.write(stmt + ";\n")
        self.proc.stdin.flush()

    def execute(self, stmt: str, timeout: float | None = None) -> Result:
        self.send(stmt)
        return self._next(stmt, timeout)

    def script(self, script: str) -> list[Result]:
        return [self.execute(s) for s in split(script)]

    def ok(self, script: str) -> list[Result]:
        res = self.script(script)
        for r in res:
            assert r.ok, f"statement failed: {r}"
        return res

    def pipeline(self, stmts: list[str], timeout: float = 120.0) -> tuple[float, list[Result]]:
        """Send ``stmts`` back to back; return (seconds until the last answer, results)."""
        data = "".join(s + ";\n" for s in stmts)

        def writer() -> None:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
        t0 = time.perf_counter()
        th = threading.Thread(target=writer, daemon=True)
        th.start()
        deadline = t0 + timeout
        res = []
        for s in stmts:
            res.append(self._next(s, max(0.1, deadline - time.perf_counter())))
        elapsed = time.perf_counter() - t0
        th.join(5)
        return elapsed, res

    def timed(self, stmt: str, timeout: float | None = None) -> tuple[float, Result]:
        t0 = time.perf_counter()
        r = self.execute(stmt, timeout)
        return time.perf_counter() - t0, r

    def kill(self) -> None:
        """SIGKILL: no shutdown code runs."""
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(10)

    def close(self, timeout: float = 30.0) -> int:
        """End of input; wait for a normal exit."""
        try:
            self.proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        return self.proc.wait(timeout)

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)
        for fh in (self.proc.stdin, self.proc.stdout):
            try:
                fh.close()
            except (OSError, ValueError):
                pass
        self._err.close()


# ------------------------------------------------------------------ assertions

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
        assert result.columns == columns, f"{result.stmt[:300]!r}: columns {result.columns}"
    assert tag(result.rows) == tag(expected), (
        f"{result.stmt[:300]!r}:\n  got      {result.rows[:50]}\n  expected {expected[:50]}")


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


def plan(result: Result) -> list[str]:
    """The plan lines of an EXPLAIN result."""
    assert result.ok, result
    assert result.columns == ["plan"], result
    return [row[0] for row in result.rows]


# ------------------------------------------------------------------ shared data

# A small schema without constraints (and without NULLs in id/name), used from section 2 on.
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

# Employees and departments with keys and constraints, used from section 6 on.
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

# Ten digits, for generating large tables with cross joins (INSERT ... SELECT, section 11).
DIGITS = """
CREATE TABLE d (x INTEGER);
INSERT INTO d VALUES (0), (1), (2), (3), (4), (5), (6), (7), (8), (9);
"""


def big_table_sql(name: str = "big", n_tens_of_thousands: int = 5, indexes: bool = True) -> str:
    """SQL (run after DIGITS) creating ``name`` with N = 10_000 * n rows (1 <= n <= 9):

    id  INTEGER PRIMARY KEY  0 .. N-1, in insertion order (nested-loop order of the cross join)
    k   INTEGER              a permutation of 0 .. N-1: (id * 7919) % N; indexed if ``indexes``
    grp INTEGER              id % 1000
    tag TEXT                 't' || (id % 97)
    val REAL                 (id % 1000) * 0.5
    """
    n = 10_000 * n_tens_of_thousands
    ident = "(a.x * 10000 + b.x * 1000 + c.x * 100 + e.x * 10 + f.x)"
    sql = (f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, k INTEGER, grp INTEGER, tag TEXT, "
           f"val REAL);\n")
    if indexes:
        sql += f"CREATE INDEX {name}_k ON {name} (k);\n"
    sql += (f"INSERT INTO {name} SELECT {ident}, ({ident} * 7919) % {n}, {ident} % 1000, "
            f"'t' || CAST({ident} % 97 AS TEXT), ({ident} % 1000) * 0.5 "
            f"FROM d a CROSS JOIN d b CROSS JOIN d c CROSS JOIN d e CROSS JOIN d f "
            f"WHERE a.x < {n_tens_of_thousands};\n")
    return sql
