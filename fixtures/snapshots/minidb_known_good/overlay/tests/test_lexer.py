import pytest
from minidb.lexer import tokenize
from minidb.protocol import SQLSyntaxError


def kinds(sql):
    return [(t.kind, t.value) for t in tokenize(sql)][:-1]


def test_keywords_identifiers_and_literals():
    assert kinds("select Name, 12, 3.5, 'it''s' FROM T") == [
        ("KW", "SELECT"), ("IDENT", "name"), ("OP", ","), ("INT", 12), ("OP", ","),
        ("REAL", 3.5), ("OP", ","), ("STR", "it's"), ("KW", "FROM"), ("IDENT", "t")]


def test_operators_and_comments():
    assert [v for _, v in kinds("a<=b <> c != d || e -- gone\n>= 1")] == [
        "a", "<=", "b", "<>", "c", "!=", "d", "||", "e", ">=", 1]


def test_errors():
    for bad in ("'open", "9223372036854775808", "a # b", "12abc"):
        with pytest.raises(SQLSyntaxError):
            tokenize(bad)
