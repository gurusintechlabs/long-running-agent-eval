"""Lexer: tokens, literals and their syntax errors."""
import pytest

from minidb.lexer import EOF, IDENT, INTEGER, KEYWORD, OP, REAL, STRING, tokenize
from minidb.protocol import SQLSyntaxError


def kinds(sql):
    return [(t.kind, t.value) for t in tokenize(sql)][:-1]


def test_keywords_are_upper_and_identifiers_lower():
    assert kinds("select Foo FROM bar_1") == [
        (KEYWORD, "SELECT"), (IDENT, "foo"), (KEYWORD, "FROM"), (IDENT, "bar_1")]


def test_type_and_function_names_are_not_reserved():
    assert kinds("integer count") == [(IDENT, "integer"), (IDENT, "count")]


def test_numbers():
    assert kinds("42 3.25 0.5") == [(INTEGER, 42), (REAL, 3.25), (REAL, 0.5)]
    assert kinds("9223372036854775807") == [(INTEGER, 9223372036854775807)]


@pytest.mark.parametrize("sql", ["5.", "12abc", "1e5", "3.5x", "9223372036854775808",
                                 "1" * 400 + ".0", "'open", "\"x\"", "@", "a#b"])
def test_malformed_tokens(sql):
    with pytest.raises(SQLSyntaxError):
        tokenize(sql)


def test_dot_five_is_a_dot_then_a_number():
    assert kinds(".5") == [(OP, "."), (INTEGER, 5)]


def test_strings_and_escaped_quotes():
    assert kinds("'it''s' ''") == [(STRING, "it's"), (STRING, "")]


def test_operators_longest_match():
    assert [v for _, v in kinds("<= <> != >= || < > = - +")] == [
        "<=", "<>", "!=", ">=", "||", "<", ">", "=", "-", "+"]


def test_comment_and_eof():
    toks = tokenize("a -- comment\n b")
    assert [t.value for t in toks[:-1]] == ["a", "b"]
    assert toks[-1].kind == EOF
