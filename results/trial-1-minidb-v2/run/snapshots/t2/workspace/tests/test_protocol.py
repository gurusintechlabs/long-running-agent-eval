"""The wire protocol layer: statement splitting, JSON encoding, error mapping."""
import io
import json

from minidb.protocol import (
    ERROR_TYPES,
    DBError,
    SQLNameError,
    StatementSplitter,
    encode_result,
    serve,
    split_statements,
)


def test_split_on_semicolons_and_skip_empty_statements():
    assert split_statements("A 1; B 2;;  ;\nC 3;") == ["A 1", "B 2", "C 3"]


def test_semicolon_and_escaped_quote_inside_string_literal():
    assert split_statements("X 'a;b'; Y 'it''s; fine';") == ["X 'a;b'", "Y 'it''s; fine'"]


def test_line_comments_are_removed():
    text = "A 1 -- trailing; not a terminator\n+ 2; -- whole line;\nB 'x--y'; C 4 - 1;"
    assert split_statements(text) == ["A 1 \n+ 2", "B 'x--y'", "C 4 - 1"]


def test_trailing_statement_without_semicolon_is_kept():
    assert split_statements("A; B") == ["A", "B"]
    assert split_statements("A; -- only a comment") == ["A"]


def test_splitter_handles_arbitrary_chunk_boundaries():
    text = "A 'x;''y' -- c;\n; B -1;"
    sp = StatementSplitter()
    got = [s for ch in text for s in sp.feed(ch)] + sp.finish()
    assert got == split_statements(text) == ["A 'x;''y'", "B -1"]


def test_encode_result_shapes():
    assert json.loads(encode_result({})) == {"ok": True}
    assert json.loads(encode_result({"rowcount": 3})) == {"ok": True, "rowcount": 3}
    line = encode_result({"columns": ["a", "b"], "rows": [[1, 1.5], ["x", True], [None, False]]})
    assert line == ('{"ok": true, "columns": ["a", "b"], '
                    '"rows": [[1, 1.5], ["x", true], [null, false]]}')


class FakeEngine:
    def execute(self, sql):
        if sql == "BOOM":
            raise ZeroDivisionError("unexpected")
        if sql == "MISSING":
            raise SQLNameError("no such table: missing")
        if sql == "BAD":
            return {"rows": object()}
        return {"rowcount": len(sql)}


def _serve(text):
    out = io.StringIO()
    serve(io.StringIO(text), out, FakeEngine())
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_one_line_per_statement_and_processing_continues_after_errors():
    res = _serve("ab; BOOM; MISSING; BAD; abcd;")
    assert len(res) == 5
    assert res[0] == {"ok": True, "rowcount": 2}
    assert res[1]["ok"] is False and res[1]["error"]["type"] == "InternalError"
    assert res[2] == {"ok": False, "error": {"type": "NameError", "message": "no such table: missing"}}
    assert res[3]["error"]["type"] == "InternalError"
    assert res[4] == {"ok": True, "rowcount": 4}


def test_error_types_are_a_fixed_set():
    assert ERROR_TYPES == {"InternalError", "SyntaxError", "NameError", "TypeError",
                           "ConstraintError", "TransactionError", "RuntimeError", "IOError",
                           "NotImplementedError"}
    assert issubclass(SQLNameError, DBError)
