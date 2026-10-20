"""Counterpart services and fixtures run by the harness (plan B3)."""
from __future__ import annotations

import sys


def stdlib_python() -> str:
    """An interpreter outside the repo for the standalone, stdlib-only counterpart scripts (fixtures,
    the ops MCP server). The repo venv's python would put the harness path in their command line,
    which the agent can see with ``ps``."""
    base = getattr(sys, "_base_executable", None)
    return base if base and ".venv" not in base else sys.executable
