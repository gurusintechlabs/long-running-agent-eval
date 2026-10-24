"""YAML that cannot blow up (UH-6).

``yaml.safe_load`` keeps aliases as shared objects, so a 12-level fan-out file is tiny in memory until
something walks it (``json.dumps`` of the loaded value, ``safe_dump``, the spec hash) and then expands
to billions of nodes. Spec text is untrusted, so the UI refuses aliases outright (real specs do not use
them) and caps the node count and the nesting depth while composing.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent

from ui_server import safefs

MAX_BYTES = 256 * 1024
MAX_NODES = 20_000
MAX_DEPTH = 48


class YamlRejected(yaml.YAMLError):
    pass


class _Loader(yaml.SafeLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self._nodes = 0
        self._depth = 0

    def compose_node(self, parent, index):
        if self.check_event(AliasEvent):
            raise YamlRejected("YAML aliases (*name) and merge keys are not accepted")
        self._nodes += 1
        if self._nodes > MAX_NODES:
            raise YamlRejected(f"YAML has more than {MAX_NODES} nodes")
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise YamlRejected(f"YAML is nested deeper than {MAX_DEPTH} levels")
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1


def load(text: str | bytes) -> Any:
    """``yaml.safe_load`` without aliases and with node/depth caps. Raises ``yaml.YAMLError`` (incl.
    ``YamlRejected``) or ``RecursionError``/``ValueError`` as ``safe_load`` would."""
    return yaml.load(text, Loader=_Loader)  # noqa: S506  (SafeLoader subclass)


def read_file(path: Path | str, limit: int = MAX_BYTES) -> str | None:
    """File text (at most ``limit`` bytes) or None when unreadable; a longer file is rejected by the
    caller via ``too_big``. Reads through ``safefs`` (final component not followed)."""
    b = safefs.read_bytes(path, limit + 1)
    if b is None:
        return None
    if len(b) > limit:
        raise YamlRejected(f"file is larger than {limit} bytes")
    return b.decode("utf-8", errors="replace")


def load_file(path: Path | str) -> Any:
    text = read_file(path)
    if text is None:
        raise OSError(f"cannot read {os.fspath(path)}")
    return load(text)


def precheck_file(path: Path | str) -> None:
    """Raise ``YamlRejected`` (or ``yaml.YAMLError``) when the file would not load safely."""
    load_file(path)


_REF_KEYS = frozenset({"prompt_file", "constraints_file", "hidden_tests", "seed_requirements_lock", "policy_file",
                       "script", "stages_file", "workspace_memory", "exploit_tests", "judge_fixtures",
                       "context_file"})


def _yaml_refs(node: Any, out: list[str], depth: int = 0) -> None:
    """Every string stored under a path-valued key of the spec."""
    if depth > MAX_DEPTH:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _REF_KEYS and isinstance(v, str):
                out.append(v)
            else:
                _yaml_refs(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _yaml_refs(v, out, depth + 1)


def _inside_repo(base: Path, ref: str, repo_root: Path) -> bool:
    q = os.path.normpath(os.path.join(base, os.path.expanduser(ref)))
    roots = {os.path.normpath(os.path.abspath(repo_root)), os.path.normpath(str(Path(repo_root).resolve()))}
    return any(q == r or q.startswith(r + os.sep) for r in roots)


def outside_ref(raw: Any, base: Path, repo_root: Path) -> str | None:
    """The first path-valued field of a spec mapping that points outside the repository (lexically, from
    ``base``: a symlink inside the repo is the repo owner's choice), else None."""
    refs: list[str] = []
    _yaml_refs(raw, refs)
    return next((r for r in refs[:50] if not _inside_repo(base, r, Path(repo_root))), None)


def load_spec_safe(path: Path | str, repo_root: Path, *, enforce_inside: bool = True):
    """``spec.loader.load_spec`` after the spec file, and every YAML file it names, passed ``load`` (no
    aliases, bounded size). The production loader uses plain ``yaml.safe_load`` and would expand a bomb."""
    from spec.loader import SpecError, load_spec
    p = Path(path).resolve()
    try:
        raw = load_file(p)
        refs: list[str] = []
        _yaml_refs(raw, refs)
        bad = outside_ref(raw, p.parent, Path(repo_root)) if enforce_inside else None
        if bad is not None:
            raise SpecError(f"{bad}: files named by a spec must be inside the repository")
        for ref in refs[:50]:
            q = Path(ref).expanduser()
            q = q if q.is_absolute() else p.parent / q
            if q.suffix.lower() in (".yaml", ".yml") and q.is_file():
                precheck_file(q)
    except SpecError:
        raise
    except (yaml.YAMLError, RecursionError, OSError, ValueError) as exc:
        raise SpecError(f"cannot read spec {p.name}: {str(exc)[:200]}") from None
    return load_spec(p, repo_root=repo_root)
