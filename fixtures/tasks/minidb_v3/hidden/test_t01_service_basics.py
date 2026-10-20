"""t01 (stage 0): the server starts, answers /healthz, and requires keys. (B6a: the first tests of the tier;
the rest of t01-t05 arrives with the stage-0 reference in B6b.)"""
from _support import Server, expect_error, run_cli, server, stage  # noqa: F401


@stage(0)
def test_healthz_without_a_key(server):  # noqa: F811
    r = server.get("/healthz", key=None)
    assert r.status == 200 and r.json() == {"status": "ok"}


@stage(0)
def test_missing_admin_key_env_exits_2_without_listening(tmp_path):
    p = run_cli(["serve", "--data-dir", str(tmp_path / "d"), "--port", "1"], env={"MINIDB_ADMIN_KEY": ""}, timeout=20)
    assert p.returncode == 2 and p.stderr.strip()


@stage(0)
def test_sql_needs_a_valid_key(server):  # noqa: F811
    expect_error(server.post("/v1/sql", {"sql": "SELECT 1;"}, key=None), 401)
    expect_error(server.post("/v1/sql", {"sql": "SELECT 1;"}, key="wrong"), 401)
