"""Lexer: turns one SQL statement into a list of tokens."""
from __future__ import annotations

from dataclasses import dataclass

from minidb.protocol import SQLSyntaxError

RESERVED = frozenset("""
    SELECT FROM WHERE AND OR NOT NULL TRUE FALSE IS IN LIKE BETWEEN AS ORDER BY ASC DESC LIMIT
    OFFSET DISTINCT GROUP HAVING INSERT INTO VALUES UPDATE SET DELETE CREATE DROP TABLE INDEX VIEW
    UNIQUE PRIMARY KEY DEFAULT ON JOIN INNER LEFT RIGHT FULL OUTER CROSS EXISTS BEGIN COMMIT
    ROLLBACK EXPLAIN ALTER ADD COLUMN
    CASE WHEN THEN ELSE END CAST UNION INTERSECT EXCEPT ALL
""".split())

INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1

# Token kinds
KEYWORD = "KEYWORD"   # value: upper-case keyword
IDENT = "IDENT"       # value: lower-case identifier
INTEGER = "INTEGER"   # value: int
REAL = "REAL"         # value: float
STRING = "STRING"     # value: str
OP = "OP"             # value: operator / punctuation text
EOF = "EOF"

_OPERATORS = ("<>", "!=", "<=", ">=", "||", "=", "<", ">", "+", "-", "*", "/", "%", "(", ")",
              ",", ".")
_IDENT_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
_DIGITS = frozenset("0123456789")
_IDENT_CHARS = _IDENT_START | _DIGITS


@dataclass(frozen=True)
class Token:
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
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in " \t\r\n\f\v":
            i += 1
        elif ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end + 1
        elif ch in _IDENT_START:
            start = i
            while i < n and sql[i] in _IDENT_CHARS:
                i += 1
            word = sql[start:i]
            upper = word.upper()
            if upper in RESERVED:
                tokens.append(Token(KEYWORD, upper, start))
            else:
                tokens.append(Token(IDENT, word.lower(), start))
        elif ch in _DIGITS:
            i = _number(sql, i, tokens)
        elif ch == "'":
            i = _string(sql, i, tokens)
        else:
            for op in _OPERATORS:
                if sql.startswith(op, i):
                    tokens.append(Token(OP, op, i))
                    i += len(op)
                    break
            else:
                raise SQLSyntaxError(f"unexpected character {ch!r} at position {i}")
    tokens.append(Token(EOF, None, n))
    return tokens


def _number(sql: str, i: int, tokens: list[Token]) -> int:
    start, n = i, len(sql)
    while i < n and sql[i] in _DIGITS:
        i += 1
    is_real = False
    if i < n and sql[i] == ".":
        if i + 1 < n and sql[i + 1] in _DIGITS:
            is_real = True
            i += 1
            while i < n and sql[i] in _DIGITS:
                i += 1
        else:
            raise SQLSyntaxError(f"malformed number {sql[start:i + 1]!r}")
    if i < n and sql[i] in _IDENT_START:
        raise SQLSyntaxError(f"malformed number {sql[start:i + 1]!r}")
    text = sql[start:i]
    if is_real:
        value = float(text)
        if value == float("inf"):
            raise SQLSyntaxError(f"REAL literal out of range: {text}")
        tokens.append(Token(REAL, value, start))
    else:
        digits = text.lstrip("0") or "0"
        # (the length test also keeps int() clear of its digit-count limit)
        if len(digits) > 19 or int(digits) > INT64_MAX:
            raise SQLSyntaxError(f"INTEGER literal out of range: {text[:30]}")
        tokens.append(Token(INTEGER, int(digits), start))
    return i


def _string(sql: str, i: int, tokens: list[Token]) -> int:
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
            tokens.append(Token(STRING, "".join(parts), start))
            return end + 1
