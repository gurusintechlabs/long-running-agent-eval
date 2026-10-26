from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    runs_dir: Path
    token: str
    port: int
    web_dist: Path
    auto_ingest: bool = False      # `lrae ui` turns it on (ui_server/autoingest.py); tests opt in

    @property
    def db_path(self) -> Path:
        return self.runs_dir / "metrics.sqlite"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        p = self.port
        return frozenset({f"127.0.0.1:{p}", f"localhost:{p}", f"[::1]:{p}"})

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset(f"http://{h}" for h in self.allowed_hosts)
