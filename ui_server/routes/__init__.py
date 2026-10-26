"""Route modules. Every module here that defines ``register(app, settings)`` is loaded by
``create_app`` before the catch-all routes, so phases add endpoints by adding a file (no edits to app.py).
Use ``ui_server.deps`` for run lookup and the read-only store."""
from __future__ import annotations

import importlib
import pkgutil


def register_all(app, settings) -> None:
    for m in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        mod = importlib.import_module(f"{__name__}.{m.name}")
        if hasattr(mod, "register"):
            mod.register(app, settings)
