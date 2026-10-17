"""minidb wire protocol: SQL statements on stdin, one JSON line per statement on stdout.

The wire format is a contract shared with every client of minidb (see README.md):

* stdin carries SQL statements, each terminated by ``;``. A ``;`` inside a single-quoted string
  literal does not terminate a statement (``''`` inside a literal is an escaped quote), and
  ``--`` starts a comment that runs to the end of the line. Empty statements are skipped. Text
  left after the last ``;`` at end of input is executed as a final statement.
* For every statement exactly one JSON line is written to stdout and flushed:
    query:                 {"ok": true, "columns": [...], "rows": [[...], ...]}
    INSERT/UPDATE/DELETE:  {"ok": true, "rowcount": N}
    anything else:         {"ok": true}
    error:                 {"ok": false, "error": {"type": "<Type>", "message": "..."}}
* After an error, processing continues with the next statement.

The engine (``minidb.engine.Engine``) receives one statement at a time, without the terminating
``;`` and with comments removed, and returns a result dict (see ``encode_result``) or raises a
``DBError`` subclass. Any other exception is reported as an ``InternalError``.
"""
from __future__ import annotations

import json
import sys
from typing import Any, TextIO


class DBError(Exception):
    """Base class of every error reported to the client; ``type_name`` is the wire type."""

    type_name = "InternalError"


class SQLSyntaxError(DBError):
    type_name = "SyntaxError"


class SQLNameError(DBError):
    type_name = "NameError"


class SQLTypeError(DBError):
    type_name = "TypeError"


class ConstraintError(DBError):
    type_name = "ConstraintError"


class TransactionError(DBError):
    type_name = "TransactionError"


class SQLRuntimeError(DBError):
    type_name = "RuntimeError"


class SQLIOError(DBError):
    type_name = "IOError"


class NotSupportedError(DBError):
    type_name = "NotImplementedError"


ERROR_TYPES = frozenset(c.type_name for c in (
    DBError, SQLSyntaxError, SQLNameError, SQLTypeError, ConstraintError, TransactionError,
    SQLRuntimeError, SQLIOError, NotSupportedError))


class StatementSplitter:
    """Incremental statement splitter. ``feed`` text in any chunks; complete statements come out."""

    def __init__(self) -> None:
        self._buf: list[str] = []
        self._state = "code"  # code | dash | comment | string | quote

    def feed(self, text: str) -> list[str]:
        out: list[str] = []
        for ch in text:
            self._step(ch, out)
        return out

    def finish(self) -> list[str]:
        """End of input: return the trailing unterminated statement, if any."""
        out: list[str] = []
        if self._state == "dash":
            self._buf.append("-")
        self._state = "code"
        self._emit(out)
        return out

    def _step(self, ch: str, out: list[str]) -> None:
        state = self._state
        if state == "comment":
            if ch == "\n":
                self._state = "code"
                self._buf.append("\n")
            return
        if state == "string":
            self._buf.append(ch)
            if ch == "'":
                self._state = "quote"  # end of literal, unless the next char is another quote
            return
        if state == "quote":
            if ch == "'":
                self._buf.append(ch)
                self._state = "string"
                return
            self._state = "code"
        elif state == "dash":
            self._state = "code"
            if ch == "-":
                self._state = "comment"
                return
            self._buf.append("-")
        if ch == "'":
            self._buf.append(ch)
            self._state = "string"
        elif ch == "-":
            self._state = "dash"
        elif ch == ";":
            self._emit(out)
        else:
            self._buf.append(ch)

    def _emit(self, out: list[str]) -> None:
        stmt = "".join(self._buf).strip()
        self._buf.clear()
        if stmt:
            out.append(stmt)


def split_statements(text: str) -> list[str]:
    """All statements in ``text`` (comments removed, without the terminating ``;``)."""
    sp = StatementSplitter()
    return sp.feed(text) + sp.finish()


_SCALARS = (type(None), bool, int, float, str)


def _check_value(v: Any) -> Any:
    if not isinstance(v, _SCALARS):
        raise TypeError(f"engine returned a value of unsupported type {type(v).__name__}")
    return v


def encode_result(result: dict) -> str:
    """JSON line for a successful statement. ``result`` is one of
    ``{"columns": [str, ...], "rows": [[value, ...], ...]}``, ``{"rowcount": int}`` or ``{}``.
    Values must be None, bool, int, float or str."""
    if not isinstance(result, dict):
        raise TypeError(f"engine returned {type(result).__name__}, expected dict")
    payload: dict[str, Any] = {"ok": True}
    if "columns" in result:
        cols = list(result["columns"])
        if not all(isinstance(c, str) for c in cols):
            raise TypeError("column names must be strings")
        rows = []
        for row in result["rows"]:
            row = [_check_value(v) for v in row]
            if len(row) != len(cols):
                raise TypeError("row width does not match the number of columns")
            rows.append(row)
        payload["columns"], payload["rows"] = cols, rows
    elif "rowcount" in result:
        if type(result["rowcount"]) is not int:
            raise TypeError("rowcount must be an int")
        payload["rowcount"] = result["rowcount"]
    elif result:
        raise TypeError(f"unexpected result keys: {sorted(result)}")
    return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def encode_error(type_name: str, message: str) -> str:
    return json.dumps({"ok": False, "error": {"type": type_name, "message": message}},
                      ensure_ascii=False)


def handle(engine: Any, stmt: str) -> str:
    """Execute one statement and return its JSON line (never raises for ordinary exceptions)."""
    try:
        return encode_result(engine.execute(stmt))
    except DBError as exc:
        return encode_error(exc.type_name, str(exc) or exc.type_name)
    except Exception as exc:  # noqa: BLE001 - every statement must produce exactly one line
        return encode_error("InternalError", f"{type(exc).__name__}: {exc}")


class _BrokenEngine:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def execute(self, stmt: str) -> dict:
        raise DBError(f"engine failed to load: {type(self.exc).__name__}: {self.exc}")


def serve(inp: TextIO, out: TextIO, engine: Any) -> None:
    """Read statements from ``inp`` as they arrive; write one flushed JSON line each to ``out``."""
    splitter = StatementSplitter()
    for line in iter(inp.readline, ""):
        for stmt in splitter.feed(line):
            out.write(handle(engine, stmt) + "\n")
            out.flush()
    for stmt in splitter.finish():
        out.write(handle(engine, stmt) + "\n")
        out.flush()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    try:
        from minidb.engine import Engine
        engine: Any = Engine()
    except Exception as exc:  # noqa: BLE001 - report per statement instead of dying silently
        engine = _BrokenEngine(exc)
    serve(sys.stdin, sys.stdout, engine)
    return 0
