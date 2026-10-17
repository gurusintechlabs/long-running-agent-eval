"""Lexer: turns one SQL statement into a list of tokens."""
from __future__ import annotations

import re
from typing import NamedTuple

from minidb.names import Ident
from minidb.protocol import SQLSyntaxError

RESERVED = frozenset("""
    SELECT FROM WHERE AND OR NOT NULL TRUE FALSE IS IN LIKE BETWEEN AS ORDER BY ASC DESC LIMIT
    OFFSET DISTINCT GROUP HAVING INSERT INTO VALUES UPDATE SET DELETE CREATE DROP TABLE INDEX VIEW
    UNIQUE PRIMARY KEY DEFAULT ON JOIN INNER LEFT RIGHT FULL OUTER CROSS EXISTS BEGIN COMMIT
    ROLLBACK EXPLAIN ALTER ADD COLUMN
    CASE WHEN THEN ELSE END CAST UNION INTERSECT EXCEPT ALL
    WITH
""".split())

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

# Token kinds
KEYWORD = "KEYWORD"   # value: upper-case keyword
IDENT = "IDENT"       # value: the identifier (an Ident: matched case-insensitively)
INTEGER = "INTEGER"   # value: int
REAL = "REAL"         # value: float
STRING = "STRING"     # value: str
OP = "OP"             # value: operator / punctuation text
EOF = "EOF"

_TWO_CHAR_OPS = frozenset({"<>", "!=", "<=", ">=", "||"})
_ONE_CHAR_OPS = frozenset("=<>+-*/%(),.")
_IDENT_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
_DIGITS = frozenset("0123456789")
_WHITESPACE = re.compile(r"[ \t\r\n\f\v]+")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"[0-9]+(\.[0-9]+)?")


class Token(NamedTuple):
    kind: str
    value: object
    pos: int

    def is_keyword(self, *words: str) -> bool:
        return self.kind == KEYWORD and self.value in words

    def is_op(self, *ops: str) -> bool:
        return self.kind == OP and self.value in ops

    def describe(self) -> str:
        if self.kind == EOF:
            return "end of statement"
        if self.kind == STRING:
            return f"string '{self.value}'"
        return repr(str(self.value))


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    append = tokens.append
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in " \t\r\n\f\v":
            i = _WHITESPACE.match(sql, i).end()
        elif ch in _IDENT_START:
            word = _WORD.match(sql, i).group()
            upper = word.upper()
            if upper in RESERVED:
                append(Token(KEYWORD, upper, i))
            else:
                append(Token(IDENT, Ident(word), i))
            i += len(word)
        elif ch in _DIGITS:
            i = _number(sql, i, append)
        elif ch == "'":
            i = _string(sql, i, append)
        elif ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end + 1
        elif sql[i:i + 2] in _TWO_CHAR_OPS:
            append(Token(OP, sql[i:i + 2], i))
            i += 2
        elif ch in _ONE_CHAR_OPS:
            append(Token(OP, ch, i))
            i += 1
        else:
            raise SQLSyntaxError(f"unexpected character {ch!r} at position {i}")
    append(Token(EOF, None, n))
    return tokens


def _number(sql: str, i: int, append) -> int:
    start, n = i, len(sql)
    m = _NUMBER.match(sql, i)
    text = m.group()
    i = m.end()
    if i < n and (sql[i] in _IDENT_START or (sql[i] == "." and m.group(1) is None)):
        # "12abc", or "5." without digits after the dot
        raise SQLSyntaxError(f"malformed number {sql[start:i + 1]!r}")
    if m.group(1) is not None:
        value = float(text)
        if value == float("inf"):
            raise SQLSyntaxError(f"REAL literal out of range: {text[:30]}")
        append(Token(REAL, value, start))
    else:
        digits = text.lstrip("0") or "0"
        # (the length test also keeps int() clear of its digit-count limit)
        if len(digits) > 19 or int(digits) > INT64_MAX:
            raise SQLSyntaxError(f"INTEGER literal out of range: {text[:30]}")
        append(Token(INTEGER, int(digits), start))
    return i


def _string(sql: str, i: int, append) -> int:
    start, n = i, len(sql)
    i += 1
    parts: list[str] = []
    while True:
        end = sql.find("'", i)
        if end < 0:
            raise SQLSyntaxError("unterminated string literal")
        parts.append(sql[i:end])
        if end + 1 < n and sql[end + 1] == "'":
            parts.append("'")
            i = end + 2
        else:
            append(Token(STRING, "".join(parts), start))
            return end + 1
