"""REA as an external MCP counterpart (J1, D-28): registered in the run's MCP config only."""
import json
from pathlib import Path

import pytest

from runner.counterparts.manager import Counterparts, read_env_file
from spec.schema import Counterparts as CounterpartsCfg


class Log:
    def __init__(self):
        self.events = []

    def __call__(self, etype, payload):
        self.events.append((etype, payload))


def make(tmp_path, cfg: dict, home: Path | None = None) -> tuple[Counterparts, Log]:
    log = Log()
    (tmp_path / "ws").mkdir(exist_ok=True)
    cps = Counterparts(CounterpartsCfg(**cfg), workspace=tmp_path / "ws", svc_dir=tmp_path / "svc",
                       art=tmp_path / "art", seed=1, emit=log, home=home)
    (tmp_path / "art").mkdir(exist_ok=True)
    return cps, log


def test_env_file_parsing(tmp_path):
    f = tmp_path / "rea.env"
    f.write_text("# comment\nREA_JADX_MCP_JAR=/t/lib/x.jar\n\nJAVA_HOME = /jdk \nEMPTY=\nexport FOO=bar\n")
    assert read_env_file(f) == {"REA_JADX_MCP_JAR": "/t/lib/x.jar", "JAVA_HOME": "/jdk", "EMPTY": "", "FOO": "bar"}
    f.write_text("not a pair\n")
    with pytest.raises(ValueError, match="rea.env:1"):
        read_env_file(f)


def test_rea_alone_is_the_only_mcp_server(tmp_path):
    home = tmp_path / "home"
    (home / "tools" / "bin").mkdir(parents=True)
    (home / "tools" / "rea.env").write_text("REA_JADX_MCP_JAR=/x.jar\n")
    cps, log = make(tmp_path, {"rea": {"command": "~/tools/bin/rea-mcp", "args": ["--quiet"],
                                       "env_file": "~/tools/rea.env"}}, home=home)
    cps.start()
    assert cps.mcp_servers == {"rea"}
    cfg = json.loads(cps.mcp_config().read_text())
    assert cfg == {"mcpServers": {"rea": {"type": "stdio", "command": str(home / "tools" / "bin" / "rea-mcp"),
                                          "args": ["--quiet"], "env": {"REA_JADX_MCP_JAR": "/x.jar"}}}}
    assert ("rea.configured", {"command": str(home / "tools" / "bin" / "rea-mcp"), "args": ["--quiet"],
                               "env_keys": ["REA_JADX_MCP_JAR"]}) in log.events
    assert cps.env() == {}
    cps.stop()


def test_rea_next_to_ops(tmp_path):
    (tmp_path / "ops.yaml").write_text("requests: []\ndefault: {decision: deny, reply: 'not here'}\n")
    cps, _ = make(tmp_path, {"ops": {"policy_file": str(tmp_path / "ops.yaml")},
                             "rea": {"command": "/abs/rea-mcp"}})
    cps.start()
    try:
        assert cps.mcp_servers == {"ops", "rea"}
        servers = json.loads(cps.mcp_config().read_text())["mcpServers"]
        assert set(servers) == {"ops", "rea"} and servers["rea"] == {"type": "stdio", "command": "/abs/rea-mcp",
                                                                     "args": [], "env": {}}
    finally:
        cps.stop()


def test_missing_env_file_fails_at_start(tmp_path):
    cps, _ = make(tmp_path, {"rea": {"command": "/abs/rea-mcp", "env_file": str(tmp_path / "nope.env")}})
    with pytest.raises(RuntimeError, match="rea env_file"):
        cps.start()


def test_no_counterparts_no_config(tmp_path):
    cps, _ = make(tmp_path, {})
    cps.start()
    assert cps.mcp_servers == set() and cps.mcp_config() is None
    cps.stop()
