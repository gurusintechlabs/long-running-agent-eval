"""One run's counterparts (D-19, plan B3): the ops channel, the mock embedding API and the process
fixtures, plus the files the agent's CLI needs to reach them.

Lifecycle (runner/orchestrator.py): started in PREPARING, before the agent env is built (the env
carries ``EMBED_URL`` / ``EMBED_API_KEY``); stage ``env_actions`` switch modes and start/stop
fixtures; :meth:`on_turn` feeds the ops check-ins; :meth:`stop` in FINALIZING. Everything is logged
to ``events/counterpart.jsonl``.

The ops MCP server script is copied into ``<work_dir>/<run_id>-svc/`` (next to the fixture scripts)
and run with an interpreter outside the repo, so the CLI's MCP config names nothing in the harness.
"""
from __future__ import annotations

import json
import secrets
import shutil
from pathlib import Path

from runner.counterparts import stdlib_python
from runner.counterparts.embed import MockEmbedding
from runner.counterparts.fixtures import FixtureSet
from runner.counterparts.ops import OpsPolicy, OpsServer, OpsService, mcp_server_script


class Counterparts:
    def __init__(self, cfg, *, workspace: Path, svc_dir: Path, art: Path, seed: int, emit,
                 honey_tokens: dict[str, str] | None = None):
        self.cfg = cfg                       # spec.task.counterparts
        self.svc_dir = Path(svc_dir)
        self.art = Path(art)
        self.emit = emit
        self.fixtures = FixtureSet(workspace=workspace, svc_dir=self.svc_dir, emit=emit)
        self.ops: OpsService | None = None
        self._ops_server: OpsServer | None = None
        self.embed: MockEmbedding | None = None
        self._embed_key = f"emb-{secrets.token_hex(12)}"
        self._seed = seed
        self._honey = dict(honey_tokens or {})

    @property
    def mcp_servers(self) -> set[str]:
        return {"ops"} if self.ops is not None else set()

    def start(self) -> Counterparts:
        self.svc_dir.mkdir(parents=True, exist_ok=True)
        if self.cfg.ops is not None:
            self.ops = OpsService(OpsPolicy.load(self.cfg.ops.policy_file), emit=self.emit)
            self._ops_server = OpsServer(self.ops)
            self._ops_server.start()
            shutil.copyfile(mcp_server_script(), self.svc_dir / "ops-mcp.py")
            self.emit("ops.started", {"url": self._ops_server.url})
        if self.cfg.embed is not None:
            self.embed = MockEmbedding(api_key=self._embed_key, dims=self.cfg.embed.dims, seed=self._seed,
                                       emit=self.emit, honey=self._honey)
            self.embed.start()
        return self

    def env(self) -> dict[str, str]:
        """Variables for the agent's environment."""
        if self.embed is None:
            return {}
        return {"EMBED_URL": self.embed.url, "EMBED_API_KEY": self._embed_key}

    def mcp_config(self) -> Path | None:
        if self._ops_server is None:
            return None
        path = self.art / "mcp.json"
        if not path.exists():
            path.write_text(json.dumps({"mcpServers": {"ops": {
                "type": "stdio", "command": stdlib_python(), "args": ["-I", str(self.svc_dir / "ops-mcp.py")],
                "env": {"LRAE_OPS_URL": self._ops_server.url}}}}, indent=1))
        return path

    def set_mode(self, service: str, mode: dict) -> dict:
        if service != "embed" or self.embed is None:
            raise RuntimeError(f"counterpart {service!r} is not running for this task")
        self.embed.set_mode(mode)
        return dict(self.embed.mode)

    def on_turn(self, turn: int) -> None:
        if self.ops is not None:
            self.ops.on_turn(turn)

    def stop(self) -> None:
        self.fixtures.stop_all()
        for svc in (self._ops_server, self.embed):
            if svc is not None:
                try:
                    svc.stop()
                except OSError:
                    pass
        shutil.rmtree(self.svc_dir, ignore_errors=True)
