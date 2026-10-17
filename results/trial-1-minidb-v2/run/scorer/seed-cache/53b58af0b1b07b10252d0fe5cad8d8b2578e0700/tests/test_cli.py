"""``python -m minidb`` end to end, as a client sees it (subprocess, stdin/stdout)."""
import json
import subprocess
import sys
from pathlib import Path

from minidb.protocol import ERROR_TYPES

ROOT = Path(__file__).resolve().parents[1]


def run(script: str) -> list[dict]:
    proc = subprocess.run([sys.executable, "-m", "minidb"], input=script, cwd=ROOT, text=True,
                          encoding="utf-8", capture_output=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines()]


def assert_error(res: dict) -> None:
    assert res["ok"] is False
    assert set(res) == {"ok", "error"}
    assert set(res["error"]) == {"type", "message"}
    assert res["error"]["type"] in ERROR_TYPES and res["error"]["type"] != "InternalError"
    assert isinstance(res["error"]["message"], str) and res["error"]["message"]


def test_invalid_statement_gives_an_error_object():
    res = run("FROBNICATE THE DATABASE;")
    assert len(res) == 1
    assert_error(res[0])


def test_one_json_line_per_statement_with_comments_and_quotes():
    script = "FROBNICATE 'a;b'; -- comment; with semicolons\n;; WIBBLE 'it''s';\nWOBBLE"
    res = run(script)
    assert len(res) == 3
    for r in res:
        assert_error(r)


def test_unterminated_string_literal_is_an_error_not_a_crash():
    res = run("FROBNICATE 'never closed")
    assert len(res) == 1
    assert_error(res[0])


def test_output_is_flushed_per_statement():
    proc = subprocess.Popen([sys.executable, "-m", "minidb"], cwd=ROOT, text=True,
                            encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    try:
        proc.stdin.write("FROBNICATE;\n")
        proc.stdin.flush()
        first = proc.stdout.readline()  # must arrive while stdin is still open
        assert_error(json.loads(first))
        proc.stdin.write("WIBBLE;\n")
        proc.stdin.close()
        assert_error(json.loads(proc.stdout.readline()))
        assert proc.wait(timeout=30) == 0
    finally:
        proc.kill()
        proc.wait()


def test_empty_input_gives_no_output():
    assert run("") == []
    assert run("  -- nothing here\n ; ;\n") == []
