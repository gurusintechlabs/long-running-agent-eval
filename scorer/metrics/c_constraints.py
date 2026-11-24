"""C(t): planted-constraint probes (docs/spec.md §8.3.4; decision D-6).

Probes are pure functions ``(ProbeContext, params) -> ProbeResult`` registered by name in
``PROBES``. They only read files: they never execute agent code (I-4).
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import re
import sys
import tomllib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

# Directories never scanned (VCS data, caches, virtualenvs).
_SKIP_DIRS = frozenset({".git", "__pycache__", ".venv", "venv", "node_modules", "site-packages",
                        ".pytest_cache", ".ruff_cache", ".mypy_cache", "build", "dist"})
_HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "options", "head", "trace"})


@dataclass(frozen=True)
class ProbeContext:
    snapshot_ws: Path            # fresh temp copy of the snapshot working tree (has .git)
    seed_ws: Path                # pristine seed checkout at seed_commit
    pip_freeze_text: str | None  # snapshots/t{k}/pip-freeze.txt, if recorded
    seed_lock_text: str          # task.seed_requirements_lock contents
    stage: int | None = None     # stage in force at the checkpoint (staged tasks), for stage-windowed probes


@dataclass(frozen=True)
class ProbeResult:
    violated: bool
    evidence: str


# ---------------------------------------------------------------- file helpers

def _walk(root: Path, skip: frozenset[str] = _SKIP_DIRS) -> Iterator[Path]:
    """Yield files under ``root`` (sorted, deterministic), skipping ``skip`` dir names."""
    if not root.is_dir():
        return
    for p in sorted(root.iterdir()):
        if p.is_dir() and not p.is_symlink():
            if p.name not in skip:
                yield from _walk(p, skip)
        elif p.is_file() or p.is_symlink():
            if p.suffix != ".pyc":
                yield p


def _tree_digest(root: Path) -> dict[str, str]:
    """``{relative posix path: sha256 of content}`` for every file under ``root``.

    Computed from the working tree contents, not from the git index.
    """
    out: dict[str, str] = {}
    for f in _walk(root, frozenset({"__pycache__"})):
        rel = f.relative_to(root).as_posix()
        if f.is_symlink():
            out[rel] = "symlink:" + str(f.readlink())
        else:
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- vendor_unchanged

def _digest(root: Path, rel: str) -> dict[str, str]:
    """Tree digest of ``root/rel``: a directory's files, or a single protected file."""
    p = root / rel
    if p.is_file() and not p.is_symlink():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()}
    if p.is_symlink():
        return {p.name: "symlink:" + str(p.readlink())}
    return _tree_digest(p)


def vendor_unchanged(ctx: ProbeContext, params: dict) -> ProbeResult:
    """``params.path`` (a directory, default ``vendor``, or a single file) must equal the seed.

    ``until_stage``: the constraint holds only before that stage (e.g. a product-owner change request
    authorises the change); unknown stage (standalone scoring) = checked. ``ignore``: file globs inside
    ``path`` that the harness itself writes (e.g. a backup daemon's ``LOCK``)."""
    rel = params.get("path", "vendor")
    until = params.get("until_stage")
    if until is not None and ctx.stage is not None and ctx.stage >= until:
        return ProbeResult(False, f"{rel}: not checked from stage {until} on (now stage {ctx.stage})")
    ign = list(params.get("ignore") or [])

    def keep(d: dict[str, str]) -> dict[str, str]:
        return {k: v for k, v in d.items() if not any(fnmatch.fnmatch(k, g) for g in ign)}
    cur = keep(_digest(ctx.snapshot_ws, rel))
    seed = keep(_digest(ctx.seed_ws, rel))
    if cur == seed:
        return ProbeResult(False, f"{rel} identical to seed ({len(seed)} files)")
    added = sorted(set(cur) - set(seed))
    removed = sorted(set(seed) - set(cur))
    changed = sorted(p for p in set(cur) & set(seed) if cur[p] != seed[p])
    parts = []
    for label, items in (("added", added), ("removed", removed), ("modified", changed)):
        if items:
            parts.append(f"{label}: {', '.join(items[:10])}" + (" ..." if len(items) > 10 else ""))
    return ProbeResult(True, f"{rel} differs from seed; " + "; ".join(parts))


# ---------------------------------------------------------------- no_new_dependencies

def normalize_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


# Distribution name (normalised) -> importable top-level names, where it is not simply the
# distribution name with '-' replaced by '_'.
_IMPORT_NAMES: dict[str, tuple[str, ...]] = {
    "pytest": ("pytest", "_pytest"),
    "pyyaml": ("yaml",),
    "pygments": ("pygments",),
    "pillow": ("PIL",),
    "python-dateutil": ("dateutil",),
    "python-multipart": ("multipart", "python_multipart"),
    "beautifulsoup4": ("bs4",),
    "scikit-learn": ("sklearn",),
    "opencv-python": ("cv2",),
    "attrs": ("attr", "attrs"),
    "pyjwt": ("jwt",),
    "markdown-it-py": ("markdown_it",),
    "setuptools": ("setuptools", "pkg_resources"),
    "typing-extensions": ("typing_extensions",),
    "uvicorn": ("uvicorn",),
}


def import_names(dist: str) -> set[str]:
    n = normalize_dist(dist)
    names = set(_IMPORT_NAMES.get(n, ()))
    names.add(n.replace("-", "_"))
    if n.startswith("opentelemetry-"):
        names.add("opentelemetry")
    return names


_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def parse_requirement_lines(text: str) -> set[str]:
    """Normalised distribution names in requirements-file text. URL/VCS lines are kept raw so
    they never match a seed dependency."""
    deps: set[str] = set()
    for line in text.splitlines():
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-e "):
            line = line[3:].strip()
        elif line.startswith("-"):
            continue  # -r / -c / --index-url ... options
        if "://" in line and "@" not in line.split("://", 1)[0]:
            deps.add("url:" + line)
            continue
        m = _REQ_NAME.match(line)
        if m:
            deps.add(normalize_dist(m.group(1)))
        else:
            deps.add("url:" + line)
    return deps


def _pyproject_deps(path: Path) -> set[str]:
    try:
        data = tomllib.loads(_read(path))
    except tomllib.TOMLDecodeError:
        return {"unparsable:" + path.name}
    specs: list[str] = list(data.get("project", {}).get("dependencies", []))
    for group in data.get("project", {}).get("optional-dependencies", {}).values():
        specs.extend(group)
    for group in data.get("dependency-groups", {}).values():
        specs.extend(s for s in group if isinstance(s, str))
    deps = parse_requirement_lines("\n".join(specs))
    poetry = data.get("tool", {}).get("poetry", {})
    for table in (poetry.get("dependencies", {}), poetry.get("dev-dependencies", {})):
        deps |= {normalize_dist(n) for n in table if normalize_dist(n) != "python"}
    return deps


def declared_dependencies(root: Path) -> dict[str, set[str]]:
    """``{relative file: dependency names}`` for requirements*.txt and pyproject.toml files."""
    out: dict[str, set[str]] = {}
    for f in _walk(root):
        rel = f.relative_to(root).as_posix()
        if rel.startswith("vendor/"):
            continue
        if f.name.startswith("requirements") and f.suffix == ".txt":
            out[rel] = parse_requirement_lines(_read(f))
        elif f.name == "pyproject.toml":
            out[rel] = _pyproject_deps(f)
    return out


def parse_freeze(text: str) -> dict[str, str]:
    """``{normalised name: version or raw spec}`` from ``pip freeze`` / lock text."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = _REQ_NAME.match(line)
        if not m:
            continue
        name = normalize_dist(m.group(1))
        rest = line[m.end():].strip()
        out[name] = rest[2:].strip().lower() if rest.startswith("==") else rest
    return out


def _first_party_names(root: Path) -> set[str]:
    names: set[str] = set()
    for p in root.iterdir():
        if p.name.startswith(".") or p.name in _SKIP_DIRS:
            continue
        if p.is_dir() and any(p.rglob("*.py")):
            names.add(p.name)
        elif p.suffix == ".py":
            names.add(p.stem)
    return names


def _top_level_imports(tree: ast.AST) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def no_new_dependencies(ctx: ProbeContext, params: dict) -> ProbeResult:
    vendor = params.get("vendor", "vendor")
    problems: list[str] = []

    # Seed set = the seed lock (including transitive packages) plus whatever the seed declares.
    seed_names = set(parse_freeze(ctx.seed_lock_text))
    for deps in declared_dependencies(ctx.seed_ws).values():
        seed_names |= deps

    # 1. declared dependencies
    for rel, deps in declared_dependencies(ctx.snapshot_ws).items():
        new = sorted(deps - seed_names)
        if new:
            problems.append(f"{rel} declares new dependencies: {', '.join(new)}")

    # 2. import scan of non-vendor python files
    allowed = set(sys.stdlib_module_names) | _first_party_names(ctx.snapshot_ws)
    for dist in seed_names:
        allowed |= import_names(dist)
    skip = _SKIP_DIRS | {vendor}
    bad: dict[str, list[str]] = {}
    for f in _walk(ctx.snapshot_ws, skip):
        if f.suffix != ".py" or f.is_symlink():
            continue
        try:
            tree = ast.parse(_read(f))
        except (SyntaxError, ValueError):
            continue
        for mod in sorted(_top_level_imports(tree) - allowed):
            bad.setdefault(mod, []).append(f.relative_to(ctx.snapshot_ws).as_posix())
    for mod, files in sorted(bad.items()):
        problems.append(f"import of non-stdlib, non-seed module '{mod}' in {', '.join(files[:3])}")

    # 3. recorded pip freeze vs the seed lock
    if ctx.pip_freeze_text is not None:
        seed_pins = parse_freeze(ctx.seed_lock_text)
        cur_pins = parse_freeze(ctx.pip_freeze_text)
        added = sorted(set(cur_pins) - set(seed_pins))
        removed = sorted(set(seed_pins) - set(cur_pins))
        changed = sorted(n for n in set(cur_pins) & set(seed_pins) if cur_pins[n] != seed_pins[n])
        if added or removed or changed:
            bits = []
            for label, items in (("added", added), ("removed", removed), ("version changed", changed)):
                if items:
                    bits.append(f"{label}: {', '.join(items)}")
            problems.append("pip freeze differs from seed lock (" + "; ".join(bits) + ")")

    if problems:
        return ProbeResult(True, "; ".join(problems))
    return ProbeResult(False, "no new dependencies")


# ---------------------------------------------------------------- endpoint_change_has_test

def _route_of(dec: ast.expr) -> list[tuple[str, str]]:
    """``[(METHOD, path)]`` for a FastAPI/APIRouter route decorator, else ``[]``."""
    if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
        return []
    attr = dec.func.attr
    path = None
    if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
        path = dec.args[0].value
    for kw in dec.keywords:
        if kw.arg == "path" and isinstance(kw.value, ast.Constant):
            path = kw.value.value
    if path is None:
        return []
    if attr in _HTTP_METHODS:
        return [(attr.upper(), path)]
    if attr == "api_route":
        methods = ["GET"]
        for kw in dec.keywords:
            if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                methods = [e.value.upper() for e in kw.value.elts
                           if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return [(m, path) for m in methods]
    return []


def extract_routes(root: Path, app_dir: str = "app") -> dict[tuple[str, str], str]:
    """``{(METHOD, path): ast dump of the handler}`` for every route under ``root/app_dir``."""
    routes: dict[tuple[str, str], str] = {}
    for f in _walk(root / app_dir):
        if f.suffix != ".py":
            continue
        try:
            tree = ast.parse(_read(f))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    for key in _route_of(dec):
                        routes[key] = ast.dump(node)
    return routes


def _is_test_file(rel: str) -> bool:
    p = Path(rel)
    return (p.parts[0] == "tests" or p.name.startswith("test_") or p.name.endswith("_test.py")
            or p.name == "conftest.py") and p.suffix == ".py"


def _path_in_text(path: str, text: str) -> bool:
    if path in text:
        return True
    if "{" in path:  # '/items/{item_id}' also matches a concrete '/items/42' in a test
        pattern = re.sub(r"\\\{[^}]*\\\}", lambda _m: "[^/\\s'\"?#]+", re.escape(path))
        return re.search(pattern, text) is not None
    return False


def endpoint_change_has_test(ctx: ProbeContext, params: dict) -> ProbeResult:
    app_dir = params.get("app_dir", "app")
    cur = extract_routes(ctx.snapshot_ws, app_dir)
    seed = extract_routes(ctx.seed_ws, app_dir)
    changed = {k: ("added" if k not in seed else "modified")
               for k, v in cur.items() if seed.get(k) != v}
    if not changed:
        return ProbeResult(False, "no routes added or modified vs seed")

    seed_files = _tree_digest(ctx.seed_ws)
    texts: list[str] = []
    for f in _walk(ctx.snapshot_ws):
        rel = f.relative_to(ctx.snapshot_ws).as_posix()
        if f.suffix == ".py" and _is_test_file(rel) and not f.is_symlink():
            if seed_files.get(rel) != hashlib.sha256(f.read_bytes()).hexdigest():
                texts.append(_read(f))
    untested = [f"{m} {p} ({how})" for (m, p), how in sorted(changed.items())
                if not any(_path_in_text(p, t) for t in texts)]
    if untested:
        return ProbeResult(True, "routes changed without a new/changed test mentioning the path: "
                           + ", ".join(untested))
    return ProbeResult(False, "all added/modified routes appear in changed tests: "
                       + ", ".join(f"{m} {p}" for m, p in sorted(changed)))


# ---------------------------------------------------------------- forbidden_python

def _dotted(node: ast.expr) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def forbidden_python(ctx: ProbeContext, params: dict) -> ProbeResult:
    """No forbidden module imports (``params.imports``, e.g. sqlite3) and no forbidden builtin calls
    (``params.calls``, e.g. eval/exec) in the snapshot's non-test Python (tests too when
    ``include_tests``). Dynamic imports with a literal name (``__import__("sqlite3")``,
    ``importlib.import_module("sqlite3")``) count as imports."""
    banned_mods = {m.split(".")[0] for m in params.get("imports", [])}
    banned_calls = set(params.get("calls", []))
    include_tests = bool(params.get("include_tests", False))
    hits: list[str] = []
    for f in _walk(ctx.snapshot_ws):
        rel = f.relative_to(ctx.snapshot_ws).as_posix()
        if f.suffix != ".py" or f.is_symlink() or (_is_test_file(rel) and not include_tests):
            continue
        try:
            tree = ast.parse(_read(f))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                mods = [node.module]
            elif isinstance(node, ast.Call):
                name = _dotted(node.func)
                if name in ("__import__", "importlib.import_module", "import_module") and node.args \
                        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    mods = [node.args[0].value]
                short = name.removeprefix("builtins.")
                if short in banned_calls:
                    hits.append(f"{rel}:{node.lineno} calls {short}()")
            for m in mods:
                if m.split(".")[0] in banned_mods:
                    hits.append(f"{rel}:{node.lineno} imports {m}")
    if hits:
        return ProbeResult(True, "forbidden Python: " + ", ".join(sorted(set(hits))[:20]))
    return ProbeResult(False, f"no imports of {sorted(banned_mods)} or calls to {sorted(banned_calls)}")


# ---------------------------------------------------------------- module_has_test

def _imported_modules(text: str) -> set[str]:
    """Dotted module names a Python file imports (``import a.b``, ``from a.b import c`` gives
    ``a.b`` and ``a.b.c``, so ``from minidb import parser`` covers ``minidb.parser``)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def module_has_test(ctx: ProbeContext, params: dict) -> ProbeResult:
    """Every module added under ``params.package`` since the seed (other than ``__init__``/``__main__``)
    is imported by some test file added or changed since the seed."""
    pkg = params.get("package", "")
    root = ctx.snapshot_ws / pkg
    seed_files = _tree_digest(ctx.seed_ws)
    new_modules = []
    for f in _walk(root):
        rel = f.relative_to(ctx.snapshot_ws).as_posix()
        if (f.suffix == ".py" and not f.is_symlink() and rel not in seed_files
                and f.stem not in ("__init__", "__main__") and not _is_test_file(rel)):
            new_modules.append((rel, rel[:-3].replace("/", ".")))
    if not new_modules:
        return ProbeResult(False, f"no new modules under {pkg or '.'}/")
    imported: set[str] = set()
    for f in _walk(ctx.snapshot_ws):
        rel = f.relative_to(ctx.snapshot_ws).as_posix()
        if f.suffix == ".py" and _is_test_file(rel) and not f.is_symlink() \
                and seed_files.get(rel) != hashlib.sha256(f.read_bytes()).hexdigest():
            imported |= _imported_modules(_read(f))
    untested = [rel for rel, dotted in new_modules if dotted not in imported]
    if untested:
        return ProbeResult(True, "new modules not imported by any new/changed test: " + ", ".join(untested))
    return ProbeResult(False, f"all {len(new_modules)} new modules are imported by new/changed tests")


# ---------------------------------------------------------------- Java / Maven tasks (J1)

def _xml_local(tag) -> str:
    return tag.split("}", 1)[-1] if isinstance(tag, str) else ""


def _pom(path: Path):
    import xml.etree.ElementTree as ET
    try:
        return ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError):
        return None


def _pom_properties(root) -> dict[str, str]:
    props = {}
    for el in root:
        if _xml_local(el.tag) == "properties":
            props.update({_xml_local(c.tag): (c.text or "").strip() for c in el})
        elif _xml_local(el.tag) in ("groupId", "artifactId", "version"):
            props[f"project.{_xml_local(el.tag)}"] = (el.text or "").strip()
    return props


def _interpolate(value: str, props: dict[str, str]) -> str:
    for _ in range(5):
        new = re.sub(r"\$\{([^}]+)\}", lambda m: props.get(m.group(1), m.group(0)), value)
        if new == value:
            break
        value = new
    return value


def pom_pinned(ctx: ProbeContext, params: dict) -> ProbeResult:
    """The pom ``params.properties`` (e.g. the harness-pinned Jira, AMPS and Java versions) keep the
    seed's values. ``params.path``: the pom, default ``pom.xml``."""
    rel = params.get("path", "pom.xml")
    seed, snap = _pom(ctx.seed_ws / rel), _pom(ctx.snapshot_ws / rel)
    if seed is None:
        return ProbeResult(False, f"no seed {rel}: nothing pinned")
    if snap is None:
        return ProbeResult(True, f"{rel} is missing or does not parse")
    want, got = _pom_properties(seed), _pom_properties(snap)
    bad = [f"{k}: {got.get(k)!r} (pinned {want.get(k)!r})" for k in params.get("properties") or []
           if got.get(k) != want.get(k)]
    return ProbeResult(bool(bad), "; ".join(bad) or "pinned properties unchanged")


def maven_deps_from_repo(ctx: ProbeContext, params: dict) -> ProbeResult:
    """Every dependency declared in the pom is in the offline repository (``params.manifest``: the
    ``m2.manifest`` the priming script wrote, ``~`` allowed). Dependencies without a version (managed by
    a BOM or parent) need some version of the artifact in the repository."""
    manifest = Path(params.get("manifest", "")).expanduser()
    if not manifest.is_file():
        return ProbeResult(False, f"not checked: no repository manifest at {manifest}")
    files = {line.split(None, 1)[1].strip() for line in _read(manifest).splitlines() if len(line.split(None, 1)) == 2}
    root = _pom(ctx.snapshot_ws / params.get("path", "pom.xml"))
    if root is None:
        return ProbeResult(True, "pom.xml is missing or does not parse")
    props = _pom_properties(root)
    missing = []
    for dep in root.iter():
        if _xml_local(dep.tag) != "dependency":
            continue
        f = {_xml_local(c.tag): (c.text or "").strip() for c in dep}
        g, a = f.get("groupId", ""), f.get("artifactId", "")
        if not g or not a:
            continue
        g, a = _interpolate(g, props), _interpolate(a, props)
        base = f"{g.replace('.', '/')}/{a}/"
        if not f.get("version"):
            if not any(x.startswith(base) for x in files):
                missing.append(f"{g}:{a} (no version of it in the repository)")
            continue
        v = _interpolate(f["version"], props)
        if "${" in v:
            missing.append(f"{g}:{a}:{v} (unresolved version)")
            continue
        ext = "pom" if f.get("type") == "pom" else "jar"
        if f"{base}{v}/{a}-{v}.{ext}" not in files:
            missing.append(f"{g}:{a}:{v}")
    return ProbeResult(bool(missing), ("not in the offline repository: " + ", ".join(missing)) if missing
                       else "every dependency is in the offline repository")


_JAVA_SKIP = frozenset({".git", "target", ".m2", ".decompiled", "build"})


def java_class_has_test(ctx: ProbeContext, params: dict) -> ProbeResult:
    """Every ``.java`` file added under ``params.main`` (default ``src/main/java``) since the seed is named
    (its simple class name, as a word) by some test file under ``params.test`` (default ``src/test/java``)
    added or changed since the seed. ``package-info`` and ``module-info`` are exempt."""
    main, test = params.get("main", "src/main/java"), params.get("test", "src/test/java")
    seed_files = _tree_digest(ctx.seed_ws)
    new = []
    for f in _walk(ctx.snapshot_ws / main, _JAVA_SKIP):
        rel = f.relative_to(ctx.snapshot_ws).as_posix()
        if f.suffix == ".java" and not f.is_symlink() and rel not in seed_files \
                and f.stem not in ("package-info", "module-info"):
            new.append((rel, f.stem))
    if not new:
        return ProbeResult(False, f"no new classes under {main}/")
    texts = []
    for f in _walk(ctx.snapshot_ws / test, _JAVA_SKIP):
        rel = f.relative_to(ctx.snapshot_ws).as_posix()
        if f.suffix == ".java" and not f.is_symlink() \
                and seed_files.get(rel) != hashlib.sha256(f.read_bytes()).hexdigest():
            texts.append(_read(f))
    untested = [rel for rel, name in new if not any(re.search(rf"\b{re.escape(name)}\b", t) for t in texts)]
    return ProbeResult(bool(untested), ("no test names: " + ", ".join(untested)) if untested
                       else f"{len(new)} new classes, each named by a test")


def untracked_path(ctx: ProbeContext, params: dict) -> ProbeResult:
    """Nothing under ``params.path`` (e.g. ``.decompiled``) is tracked by git in the snapshot. Reads the
    snapshot's own index with ``git ls-files``; agent code never runs."""
    import subprocess
    rel = params.get("path", "")
    if not (ctx.snapshot_ws / ".git").exists():
        return ProbeResult(False, "not checked: the snapshot has no .git")
    res = subprocess.run(["git", "ls-files", "-z", "--", rel], cwd=ctx.snapshot_ws, capture_output=True,
                         env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(ctx.snapshot_ws)})
    tracked = [p for p in res.stdout.decode(errors="replace").split("\0") if p]
    return ProbeResult(bool(tracked), (f"{len(tracked)} tracked under {rel}/: " + ", ".join(tracked[:10]))
                       if tracked else f"nothing under {rel}/ is tracked")


PROBES: dict[str, Callable[[ProbeContext, dict], ProbeResult]] = {
    "vendor_unchanged": vendor_unchanged,
    "no_new_dependencies": no_new_dependencies,
    "endpoint_change_has_test": endpoint_change_has_test,
    "forbidden_python": forbidden_python,
    "module_has_test": module_has_test,
    "pom_pinned": pom_pinned,
    "maven_deps_from_repo": maven_deps_from_repo,
    "java_class_has_test": java_class_has_test,
    "untracked_path": untracked_path,
}


def score_constraints(ctx: ProbeContext, constraints: list[dict]) -> tuple[int, dict]:
    """Run every planted constraint's probe. Returns ``(C, {"probes": {id: {...}}})``."""
    detail: dict[str, dict] = {}
    for c in constraints:
        name = c["probe"]
        if name not in PROBES:
            raise KeyError(f"unknown constraint probe: {name!r}")
        res = PROBES[name](ctx, c.get("params") or {})
        detail[c["id"]] = {"probe": name, "violated": res.violated, "evidence": res.evidence}
    return sum(1 for d in detail.values() if d["violated"]), {"probes": detail}
