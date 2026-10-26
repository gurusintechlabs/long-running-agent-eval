"""t01 (stage 0): starting and stopping the server, the data dir and its writer lock, keys (brief 0.1, 0.2)."""
import fcntl
import os
import signal
import subprocess
import threading
import time

from _support import (Server, expect_error, free_port, run_cli, server, stage,  # noqa: F401
                      tree_state)

SLOW_ROWS = 1200          # a self cross join of this many rows takes about 1.5 s in the inherited engine


def _serve_args(data_dir, port=None):
    return ["serve", "--data-dir", str(data_dir), "--port", str(port or free_port())]


def _initialised_dir(tmp_path):
    """A data dir created by the server itself, holding one table."""
    s = Server(tmp_path / "init")
    try:
        s.sql("CREATE TABLE kept (a INTEGER); INSERT INTO kept VALUES (1);")
    finally:
        assert s.stop() == 0
    return s.data_dir


def _slow_table(srv, name):
    rows = ",".join(f"({i})" for i in range(SLOW_ROWS))
    res = srv.sql(f"CREATE TABLE {name} (x INTEGER); INSERT INTO {name} VALUES {rows};")
    assert res[1] == {"ok": True, "rowcount": SLOW_ROWS}, res


def _slow_query(name):
    return f"SELECT COUNT(*) FROM {name} a CROSS JOIN {name} b WHERE a.x < b.x;"


@stage(0)
def test_healthz_without_a_key(server):  # noqa: F811
    r = server.get("/healthz", key=None)
    assert r.status == 200 and r.json() == {"status": "ok"} and r.ctype == "application/json"


@stage(0)
def test_missing_admin_key_env_exits_2_without_listening(tmp_path):
    p = run_cli(["serve", "--data-dir", str(tmp_path / "d"), "--port", "1"], env={"MINIDB_ADMIN_KEY": ""}, timeout=20)
    assert p.returncode == 2 and p.stderr.strip()


@stage(0)
def test_unset_admin_key_exits_2(tmp_path):
    p = run_cli(_serve_args(tmp_path / "d"), timeout=20)
    assert p.returncode == 2 and p.stderr.strip()


@stage(0)
def test_sql_needs_a_valid_key(server):  # noqa: F811
    expect_error(server.post("/v1/sql", {"sql": "SELECT 1;"}, key=None), 401)
    expect_error(server.post("/v1/sql", {"sql": "SELECT 1;"}, key="wrong"), 401)
    expect_error(server.post("/v1/sql", {"sql": "SELECT 1;"}, key=server.admin_key + "x"), 401)
    for header in (f"Basic {server.admin_key}", "Bearer", server.admin_key):
        expect_error(server.post("/v1/sql", {"sql": "SELECT 1;"}, key=None, headers={"Authorization": header}), 401)
    assert server.post("/v1/sql", {"sql": "SELECT 1;"}).status == 200


@stage(0, 11)   # CR-5 (format 2): replaced in t21
def test_a_new_data_dir_is_initialised_as_format_1(server):  # noqa: F811
    assert (server.data_dir / "FORMAT").read_text().strip() == "minidb-data 1"


@stage(0, 11)   # CR-5 (format 2): replaced in t21
def test_an_existing_empty_dir_is_initialised(tmp_path):
    (tmp_path / "empty").mkdir()
    with Server(tmp_path, data_dir=tmp_path / "empty") as s:
        assert s.sql("SELECT 1;") == [{"ok": True, "columns": ["?column?"], "rows": [[1]]}]
    assert (tmp_path / "empty" / "FORMAT").read_text().strip() == "minidb-data 1"


@stage(0, 11)   # CR-5 (format 2): replaced in t21
def test_another_format_is_refused_and_left_unchanged(tmp_path):
    for fmt in ("minidb-data 2\n", "something else\n"):
        d = tmp_path / f"dir{len(fmt)}"
        d.mkdir()
        (d / "FORMAT").write_text(fmt)
        (d / "payload.bin").write_bytes(b"\x00\x01important")
        before = tree_state(d)
        p = run_cli(_serve_args(d), env={"MINIDB_ADMIN_KEY": "k"}, timeout=20)
        assert p.returncode == 2 and p.stderr.strip(), (fmt, p.returncode, p.stderr)
        assert tree_state(d) == before, fmt


@stage(0)
def test_busy_lock_exits_3_names_the_holder_and_changes_nothing(tmp_path):
    d = _initialised_dir(tmp_path)
    fd = os.open(d / "LOCK", os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, b"backup-daemon pid 4242\n")
        before = tree_state(d)
        try:
            p = run_cli(_serve_args(d), env={"MINIDB_ADMIN_KEY": "k"}, timeout=20)
        except subprocess.TimeoutExpired:
            raise AssertionError("the server started (or hung) although the writer lock was held") from None
        assert p.returncode == 3, (p.returncode, p.stderr)
        assert "backup-daemon pid 4242" in p.stderr
        assert tree_state(d) == before
    finally:
        os.close(fd)


@stage(0)
def test_the_server_holds_the_writer_lock_while_it_runs(server):  # noqa: F811
    fd = os.open(server.data_dir / "LOCK", os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise AssertionError("the writer lock is free while the server runs")
        assert server.stop() == 0
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # released at exit
    finally:
        os.close(fd)


@stage(0)
def test_sigterm_and_sigint_stop_the_server_with_status_0(tmp_path):
    for sig in (signal.SIGTERM, signal.SIGINT):
        s = Server(tmp_path / sig.name)
        try:
            s.sql("SELECT 1;")
            t0 = time.monotonic()
            s.proc.send_signal(sig)
            try:
                rc = s.proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                raise AssertionError(f"still running 6 s after {sig.name}") from None
            assert rc == 0 and time.monotonic() - t0 < 6, (sig.name, rc)
        finally:
            s.close()


@stage(0)
def test_requests_in_flight_finish_on_sigterm(server):  # noqa: F811
    _slow_table(server, "slow")
    out = {}

    def run():
        out["r"] = server.post("/v1/sql", {"sql": _slow_query("slow")}, timeout=30)
    th = threading.Thread(target=run)
    th.start()
    time.sleep(0.4)
    server.proc.send_signal(signal.SIGTERM)
    th.join(30)
    assert out["r"].status == 200, out["r"]
    assert out["r"].json()["results"] == [{"ok": True, "columns": ["count"], "rows": [[SLOW_ROWS * (SLOW_ROWS - 1) // 2]]}]
    assert server.proc.wait(timeout=10) == 0
    try:
        server.get("/healthz", key=None, timeout=2)
    except OSError:
        pass
    else:
        raise AssertionError("still accepting requests after SIGTERM")


@stage(0)
def test_health_is_answered_while_a_long_query_runs(server):  # noqa: F811
    _slow_table(server, "slow")
    th = threading.Thread(target=lambda: server.post("/v1/sql", {"sql": _slow_query("slow")}, timeout=30))
    th.start()
    try:
        time.sleep(0.3)
        t0 = time.monotonic()
        assert server.get("/healthz", key=None, timeout=5).status == 200
        assert time.monotonic() - t0 < 0.8, "requests are not served concurrently"
    finally:
        th.join(30)


@stage(0)
def test_a_crashed_server_restarts_on_its_data_dir(server):  # noqa: F811
    server.sql("CREATE TABLE c (a INTEGER); INSERT INTO c VALUES (1), (2);")
    server.restart(crash=True)
    assert server.sql("SELECT SUM(a) FROM c;")[0]["rows"] == [[3]]


@stage(0)
def test_a_port_in_use_is_an_error_not_a_hang(server, tmp_path):  # noqa: F811
    try:
        p = run_cli(_serve_args(tmp_path / "other", server.port), env={"MINIDB_ADMIN_KEY": "k"}, timeout=20)
    except subprocess.TimeoutExpired:
        raise AssertionError("a second server on a busy port did not exit") from None
    assert p.returncode != 0 and p.stderr.strip()
