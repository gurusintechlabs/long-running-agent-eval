"""Tokenizer for minidb SQL."""
from __future__ import annotations

from dataclasses import dataclass

from minidb.protocol import SQLSyntaxError

KEYWORDS = frozenset("""
SELECT FROM WHERE AND OR NOT NULL TRUE FALSE IS IN LIKE BETWEEN AS ORDER BY ASC DESC LIMIT OFFSET
DISTINCT GROUP HAVING INSERT INTO VALUES UPDATE SET DELETE CREATE DROP TABLE INDEX VIEW UNIQUE
PRIMARY KEY DEFAULT ON JOIN INNER LEFT RIGHT FULL OUTER CROSS EXISTS BEGIN COMMIT ROLLBACK EXPLAIN
ALTER ADD COLUMN CASE WHEN THEN ELSE END CAST UNION INTERSECT EXCEPT ALL WITH
""".split())

INT_MIN, INT_MAX = -(2 ** 63), 2 ** 63 - 1
_TWO_CHAR = ("<=", ">=", "<>", "!=", "||")
_ONE_CHAR = set("=<>+-*/%(),.")
_DIGITS = frozenset("0123456789")
_IDENT_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_CHARS = _IDENT_START | _DIGITS


@dataclass(frozen=True)
class Token:
    kind: str      # INT, REAL, STR, IDENT, KW, OP, EOF
    value: object  # int / float / str; keywords upper-case, identifiers lower-case
    pos: int

    def is_kw(self, *words: str) -> bool:
        return self.kind == "KW" and self.value in words

    def is_op(self, *ops: str) -> bool:
        return self.kind == "OP" and self.value in ops


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
        elif ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif ch in _DIGITS:
            j = i
            while j < n and sql[j] in _DIGITS:
                j += 1
            if j + 1 < n and sql[j] == "." and sql[j + 1] in _DIGITS:
                j += 1
                while j < n and sql[j] in _DIGITS:
                    j += 1
                value = float(sql[i:j])
                if value == float("inf"):
                    raise SQLSyntaxError(f"real literal out of range: {sql[i:j][:30]}")
                tokens.append(Token("REAL", value, i))
            else:
                value = int(sql[i:j])
                if value > INT_MAX:
                    raise SQLSyntaxError(f"integer literal out of range: {sql[i:j]}")
                tokens.append(Token("INT", value, i))
            if j < n and sql[j] in _IDENT_CHARS:
                raise SQLSyntaxError(f"malformed number near {sql[i:j + 1]!r}")
            i = j
        elif ch in _IDENT_START:
            j = i
            while j < n and sql[j] in _IDENT_CHARS:
                j += 1
            word = sql[i:j]
            if word.upper() in KEYWORDS:
                tokens.append(Token("KW", word.upper(), i))
            else:
                tokens.append(Token("IDENT", word.lower(), i))
            i = j
        elif ch == "'":
            j, parts = i + 1, []
            while True:
                if j >= n:
                    raise SQLSyntaxError("unterminated string literal")
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        parts.append("'")
                        j += 2
                        continue
                    break
                parts.append(sql[j])
                j += 1
            tokens.append(Token("STR", "".join(parts), i))
            i = j + 1
        elif sql[i:i + 2] in _TWO_CHAR:
            tokens.append(Token("OP", sql[i:i + 2], i))
            i += 2
        elif ch in _ONE_CHAR:
            tokens.append(Token("OP", ch, i))
            i += 1
        else:
            raise SQLSyntaxError(f"unexpected character {ch!r}")
    tokens.append(Token("EOF", None, n))
    return tokens
