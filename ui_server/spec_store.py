"""Spec files for the editor: listing, validation, stable YAML output, and drafts-only writes.

Validation reuses production code: ``spec.schema.Spec`` for structure (to get field-addressed errors) and
``spec.loader.load_spec`` for everything else (files exist, hash, run ids). Spec text is untrusted: YAML is read
with ``safe_load`` only, names are matched against an allowlist, and the only directory ever written is the
drafts dir (``spec/drafts``).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin

import yaml
from pydantic import BaseModel, ValidationError

from spec.loader import _PATH_FIELDS, SpecError, _resolve
from spec.schema import Spec
from ui_server import safeyaml
from ui_server.safety import scrub_paths

NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}", re.ASCII)
MAX_YAML_BYTES = 256 * 1024
HEADER = ("# Saved by the LRAE UI spec editor. Comments from earlier versions are not preserved.\n"
          "# Keys follow the schema order (spec/schema.py).\n")


class StoreError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


RESERVED = frozenset({"schema", "validate", "save", "paths"})   # names of static /api/specs/* routes


def valid_name(name: object) -> bool:
    return (isinstance(name, str) and NAME_RE.fullmatch(name) is not None and not name.endswith(".")
            and name not in RESERVED)


# --- paths -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SpecDirs:
    repo_root: Path

    @property
    def examples(self) -> Path:
        return self.repo_root / "spec" / "examples"

    @property
    def drafts(self) -> Path:
        return self.repo_root / "spec" / "drafts"

    def ensure_drafts(self) -> Path:
        """The drafts dir, created on demand. Refuses a symlink or anything that resolves elsewhere."""
        spec_dir = (self.repo_root / "spec").resolve()
        d = self.drafts
        if d.is_symlink():
            raise StoreError(500, "spec/drafts is a symlink; refusing to write")
        d.mkdir(parents=False, exist_ok=True)
        if d.resolve().parent != spec_dir:
            raise StoreError(500, "spec/drafts resolves outside spec/; refusing to write")
        return d.resolve()

    def locate(self, name: str, source: str | None = None) -> tuple[str, Path] | None:
        """(source, file) for an existing spec. Without ``source``, a draft shadows an example."""
        if not valid_name(name):
            return None
        order = [source] if source in ("draft", "example") else ["draft", "example"]
        for src in order:
            base = self.drafts if src == "draft" else self.examples
            f = base / f"{name}.yaml"
            if f.is_symlink() or not f.is_file():
                continue
            try:
                if f.resolve().parent != base.resolve():
                    continue
            except OSError:
                continue
            return src, f
        return None


# --- data preparation --------------------------------------------------------------------------------

def _model_of(ann: Any) -> tuple[type[BaseModel] | None, bool, bool]:
    """(model class, is_list, nullable) for a field annotation."""
    nullable = False
    if get_origin(ann) in (Union, UnionType):
        args = [a for a in get_args(ann) if a is not type(None)]
        nullable = len(args) != len(get_args(ann))
        ann = args[0] if len(args) == 1 else ann
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann, False, nullable
    if get_origin(ann) is list and get_args(ann):
        inner = get_args(ann)[0]
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return inner, True, nullable
    return None, False, nullable


def prepare(data: Any, model: type[BaseModel] = Spec) -> Any:
    """Form data to spec data: drop nulls and empty strings of optional fields, order keys by the schema.
    Unknown keys are kept (after the known ones) so validation can reject them by name."""
    if not isinstance(data, dict):
        return data
    by_key = {(fi.alias or n): fi for n, fi in model.model_fields.items()}
    out: dict[str, Any] = {}
    for key in list(by_key) + [k for k in data if k not in by_key]:
        if key not in data:
            continue
        v = data[key]
        fi = by_key.get(key)
        if fi is not None:
            sub, is_list, nullable = _model_of(fi.annotation)
            if v is None and (nullable or not fi.is_required()):
                continue
            if v == "" and nullable:
                continue
            if sub is not None:
                v = [prepare(x, sub) for x in v] if is_list and isinstance(v, list) else prepare(v, sub)
        out[key] = v
    return out


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):  # indent list items under their key
        return super().increase_indent(flow, False)


def _flow_scalars(dumper: yaml.SafeDumper, data: list):
    flow = all(isinstance(x, (str, int, float, bool)) and not (isinstance(x, str) and len(x) > 40) for x in data) \
        and len(data) <= 6
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


def _str(dumper: yaml.SafeDumper, data: str):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(list, _flow_scalars)
_Dumper.add_representer(str, _str)


def dump_yaml(data: dict) -> str:
    """Deterministic, readable YAML (schema key order, no comments)."""
    return HEADER + yaml.dump(data, Dumper=_Dumper, sort_keys=False, default_flow_style=False,
                              allow_unicode=True, width=110)


def parse_yaml(text: str) -> Any:
    if not isinstance(text, str) or len(text.encode("utf-8", "replace")) > MAX_YAML_BYTES:
        raise StoreError(413, f"spec text is larger than {MAX_YAML_BYTES} bytes")
    try:
        return safeyaml.load(text)
    except (yaml.YAMLError, RecursionError, ValueError) as exc:
        raise StoreError(400, f"not valid YAML: {str(exc)[:300]}") from exc


# --- validation --------------------------------------------------------------------------------------

@dataclass
class Check:
    valid: bool
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    spec_hash: str | None = None
    run_ids: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings,
                "spec_hash": self.spec_hash, "run_ids": self.run_ids, "summary": self.summary}


def dotted(loc: tuple) -> str:
    return ".".join(str(p) for p in loc)


def _clean_msg(msg: str) -> str:
    return re.sub(r"^(Value error|Assertion failed), ", "", msg)


def _error_from_spec_error(msg: str) -> dict:
    """SpecError messages from the loader look like ``task.prompt_file: file does not exist: ...``."""
    m = re.match(r"^(?P<path>[a-z_]+(?:\.[a-z_]+)+): (?P<msg>.*)$", msg, re.S)
    if m:
        return {"path": m["path"], "message": m["msg"], "type": "loader"}
    if msg.startswith("task.prompt_file"):
        return {"path": "task.prompt_file", "message": msg, "type": "loader"}
    if "work_dir" in msg:
        return {"path": "isolation.work_dir", "message": msg, "type": "loader"}
    return {"path": "", "message": msg, "type": "loader"}


@lru_cache(maxsize=1)
def _field_paths() -> frozenset[str]:
    from ui_server.spec_ui import build_form_schema, iter_fields
    return frozenset(f["path"] for f in iter_fields(build_form_schema()["fields"]))


def _refine(err: dict) -> dict:
    """Model-level validators report on the whole object (``agent``, ``run``). When the message names one of its
    fields, point at that field so the form can mark it; ``group`` keeps the original location."""
    p, msg = err["path"], err["message"]
    paths = _field_paths()
    if not p or p not in paths or p.count("*"):
        return err
    children = {q: q[len(p) + 1:] for q in paths if q.startswith(p + ".") and q.count(".") == p.count(".") + 1}
    if not children:
        return err
    for use_full in (True, False):   # a full dotted path in the message beats a bare field name
        hits = sorted((m.start(), q) for q, n in children.items()
                      if (m := re.search(rf"\b{re.escape(q if use_full else n)}\b", msg)))
        if hits:
            return {**err, "path": hits[0][1], "group": p}
    return err


def _absolutize(raw: dict, base: Path) -> dict:
    """Copy with every path field resolved the way ``load_spec`` does (relative to the spec's directory), so the
    data can be loaded from a temporary file elsewhere with identical results."""
    d = json.loads(json.dumps(raw))

    def fix(obj: Any, key: str) -> None:
        if isinstance(obj, dict) and isinstance(obj.get(key), str):
            obj[key] = _resolve(base, obj[key])

    for section, fld in _PATH_FIELDS + [("task", "seed_repo")]:
        fix(d.get(section), fld)
    fix(((d.get("scoring") or {}).get("behavior")), "judge_fixtures")
    fix(((d.get("scoring") or {}).get("security")), "context_file")
    fix((((d.get("task") or {}).get("counterparts") or {}).get("ops")), "policy_file")
    return d


def warnings_for(spec: Spec) -> list[dict]:
    w: list[dict] = []

    def add(path: str, text: str, level: str = "warning") -> None:
        w.append({"path": path, "message": text, "level": level})

    if spec.agent.runtime == "claude_code":
        add("agent.runtime", "claude_code runtime spends real money: runs use subscription usage "
            "(API-equivalent estimate). Launching needs an explicit spend confirmation.")
    if spec.scoring.judge_runtime == "claude_code":
        add("scoring.judge_runtime", "Real judges (claude_code) also spend subscription usage.")
    if spec.scoring.security.enabled and spec.scoring.security.ai_review:
        add("scoring.security.ai_review", "The AI vulnerability review spends usage once per completed stage.")
    runs = len(spec.run.configs) * spec.run.repeats
    if spec.budget.per_run_usd > 25:
        add("budget.per_run_usd", f"High per-run cap: ${spec.budget.per_run_usd:g}.")
    if spec.budget.experiment_usd > 100:
        add("budget.experiment_usd", f"High experiment cap: ${spec.budget.experiment_usd:g}.")
    if spec.budget.experiment_usd < spec.budget.per_run_usd:
        add("budget.experiment_usd", "The experiment cap is below the per-run cap; only one run could start.")
    elif spec.agent.runtime == "claude_code" and runs * spec.budget.per_run_usd > spec.budget.experiment_usd:
        add("budget.experiment_usd", f"{runs} runs at the per-run cap "
            f"(${runs * spec.budget.per_run_usd:g}) exceed the experiment cap; later runs will not start.", "info")
    if spec.run.duration_min > 480:
        add("run.duration_min", f"A single run is planned for {spec.run.duration_min:g} minutes.", "info")
    if spec.run.parallelism > 1:
        add("run.parallelism", "The UI launches one run at a time; parallelism above 1 only applies to the CLI.", "info")
    return w


def check(raw: Any, base_dir: Path, repo_root: Path) -> Check:
    """Validate spec data exactly like ``lrae validate`` would for a file in ``base_dir``."""
    if not isinstance(raw, dict):
        return Check(False, [{"path": "", "message": "a spec must be a mapping of keys to values", "type": "type"}])
    try:
        Spec.model_validate(raw)
    except ValidationError as exc:
        errs = [_refine({"path": dotted(e["loc"]), "message": _clean_msg(e["msg"]), "type": e["type"]})
                for e in exc.errors(include_url=False, include_context=False, include_input=False)]
        return Check(False, errs)
    except Exception as exc:  # noqa: BLE001 (e.g. a validator raising on odd input)
        return Check(False, [{"path": "", "message": f"invalid spec: {exc}", "type": "error"}])
    bad = safeyaml.outside_ref(raw, base_dir, repo_root)
    if bad is not None:
        return Check(False, [{"path": "", "type": "loader",
                              "message": f"{bad}: files named by a spec must be inside the repository"}])
    try:
        with tempfile.TemporaryDirectory(prefix="lrae-validate-") as tmp:
            f = Path(tmp) / "spec.yaml"
            f.write_text(yaml.safe_dump(_absolutize(raw, base_dir), sort_keys=False))
            loaded = safeyaml.load_spec_safe(f, repo_root, enforce_inside=False)
    except SpecError as exc:
        err = _error_from_spec_error(str(exc))
        err["message"] = scrub_paths(err["message"], repo_root, Path.home())
        return Check(False, [err])
    s = loaded.spec
    ids = [loaded.run_id(c, r) for c in s.run.configs for r in range(s.run.repeats)]
    summary = {"experiment_id": s.experiment_id, "runtime": s.agent.runtime, "model": s.agent.model,
               "claude_code_version": s.agent.claude_code_version, "checkpoints": s.run.checkpoint_count,
               "checkpoint_interval_min": s.run.checkpoint_interval_min, "duration_min": s.run.duration_min,
               "configs": list(s.run.configs), "repeats": s.run.repeats, "per_run_usd": s.budget.per_run_usd,
               "experiment_usd": s.budget.experiment_usd, "runs": len(ids)}
    return Check(True, [], warnings_for(s), loaded.spec_hash, ids, summary)


def check_text_or_data(data: Any, text: str | None, dirs: SpecDirs) -> tuple[Any, Check]:
    """Prepared data and its check, for a request carrying ``data`` or ``yaml``. Paths are resolved against the
    drafts dir, which is where a saved spec lives."""
    if (data is None) == (text is None):
        raise StoreError(400, "send exactly one of 'data' or 'yaml'")
    raw = parse_yaml(text) if text is not None else data
    if isinstance(raw, dict):
        try:
            if len(json.dumps(raw)) > MAX_YAML_BYTES:
                raise StoreError(413, "spec data is too large")
        except (TypeError, ValueError) as exc:
            raise StoreError(400, f"spec data is not plain JSON: {exc}") from exc
    prepared = prepare(raw)
    res = check(prepared, dirs.drafts, dirs.repo_root)
    if res.valid:
        res.warnings += _duplicate_id_warning(prepared, dirs)
    return prepared, res


def _raw_and_reason(f: Path) -> tuple[dict | None, str | None]:
    """The spec mapping in ``f`` (aliases refused, size/node/depth bounded) or ``(None, why)``."""
    try:
        v = safeyaml.load_file(f)
    except (OSError, yaml.YAMLError, RecursionError, ValueError) as exc:
        return None, f"not a readable YAML mapping: {str(exc)[:200]}"
    return (v, None) if isinstance(v, dict) else (None, "not a readable YAML mapping")


def _raw_of(f: Path) -> dict | None:
    return _raw_and_reason(f)[0]


def _duplicate_id_warning(prepared: dict, dirs: SpecDirs, exclude: str | None = None) -> list[dict]:
    eid = prepared.get("experiment_id")
    same = [f"{src}/{n}" for src, n, f in _iter_files(dirs)
            if n != exclude and (_raw_of(f) or {}).get("experiment_id") == eid]
    if not same:
        return []
    return [{"path": "experiment_id", "level": "info",
             "message": f"experiment_id is also used by {', '.join(same[:4])}. Runs of equal specs share run IDs."}]


# --- listing / reading / writing -----------------------------------------------------------------------

def _iter_files(dirs: SpecDirs):
    for src, base in (("example", dirs.examples), ("draft", dirs.drafts)):
        if not base.is_dir() or base.is_symlink():
            continue
        for f in sorted(base.glob("*.yaml")):
            if f.is_symlink() or not f.is_file() or not valid_name(f.stem):
                continue
            yield src, f.stem, f


def entry_for(dirs: SpecDirs, src: str, name: str, f: Path) -> dict:
    raw, why = _raw_and_reason(f)
    res = check(prepare(raw), f.parent, dirs.repo_root) if raw is not None else \
        Check(False, [{"path": "", "message": why, "type": "yaml"}])
    agent = (raw or {}).get("agent") if isinstance((raw or {}).get("agent"), dict) else {}
    return {"name": name, "source": src, "editable": src == "draft",
            "path": f.relative_to(dirs.repo_root).as_posix(),
            "valid": res.valid, "spec_hash": res.spec_hash, "errors": res.errors[:3],
            "experiment_id": (raw or {}).get("experiment_id"), "runtime": agent.get("runtime"),
            "model": agent.get("model"), "mtime": f.stat().st_mtime}


def list_specs(dirs: SpecDirs) -> list[dict]:
    return [entry_for(dirs, src, name, f) for src, name, f in _iter_files(dirs)]


def load_one(dirs: SpecDirs, name: str, source: str | None) -> dict:
    hit = dirs.locate(name, source)
    if hit is None:
        raise StoreError(404, "no such spec")
    src, f = hit
    try:
        text = safeyaml.read_file(f) or ""
    except yaml.YAMLError as exc:
        raise StoreError(413, str(exc)) from None
    raw = _raw_of(f)
    e = entry_for(dirs, src, name, f)
    res = check(prepare(raw), f.parent, dirs.repo_root) if raw is not None else Check(False)
    return {**e, "data": raw, "yaml": text, "warnings": res.warnings, "run_ids": res.run_ids,
            "summary": res.summary, "validation": res.to_json()}


def _atomic_write(target_dir: Path, name: str, text: str, overwrite: bool) -> Path:
    target = target_dir / f"{name}.yaml"
    if target.is_symlink():
        raise StoreError(409, "refusing to write over a symlink")
    if target.exists() and not overwrite:
        raise StoreError(409, f"draft '{name}' already exists; send overwrite=true to replace it")
    tmp = target_dir / f".tmp-{secrets.token_hex(6)}"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if overwrite:
            os.replace(tmp, target)
        else:
            try:
                os.link(tmp, target)      # fails if the name appeared since the check: never replaces
            except FileExistsError:
                raise StoreError(409, f"draft '{name}' already exists; send overwrite=true to replace it") from None
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


def save_draft(dirs: SpecDirs, name: str, data: Any, text: str | None, overwrite: bool) -> dict:
    if not valid_name(name):
        raise StoreError(400, "name must match ^[a-z0-9][a-z0-9._-]{0,63}$ and must not end with '.'")
    d = dirs.ensure_drafts()
    prepared, res = check_text_or_data(data, text, dirs)
    if not res.valid:
        return {"saved": False, **res.to_json()}
    out = dump_yaml(prepared)
    target = _atomic_write(d, name, out, overwrite)
    # belt and braces: the file on disk must load with the hash that was validated
    try:
        again = safeyaml.load_spec_safe(target, dirs.repo_root)
        ok = again.spec_hash == res.spec_hash
    except SpecError:
        ok = False
    if not ok:
        target.unlink(missing_ok=True)
        raise StoreError(500, "saved file did not reload with the validated hash; it was removed")
    return {"saved": True, "name": name, "source": "draft", "path": target.relative_to(dirs.repo_root).as_posix(),
            **res.to_json()}


def duplicate(dirs: SpecDirs, name: str, new_name: str | None, source: str | None, overwrite: bool = False) -> dict:
    hit = dirs.locate(name, source)
    if hit is None:
        raise StoreError(404, "no such spec")
    _src, f = hit
    new = new_name or f"{name}-copy"
    if not valid_name(new):
        raise StoreError(400, "new_name must match ^[a-z0-9][a-z0-9._-]{0,63}$ and must not end with '.'")
    d = dirs.ensure_drafts()
    try:
        text = safeyaml.read_file(f) or ""
    except yaml.YAMLError as exc:
        raise StoreError(413, str(exc)) from None
    raw = parse_yaml(text)
    res = check(prepare(raw), dirs.drafts, dirs.repo_root)
    if not res.valid:
        return {"saved": False, **res.to_json()}
    # verbatim copy: keeps comments; drafts sit at the same depth as examples, so relative paths still resolve
    target = _atomic_write(d, new, text, overwrite)
    return {"saved": True, "name": new, "source": "draft", "path": target.relative_to(dirs.repo_root).as_posix(),
            **res.to_json()}


def delete_draft(dirs: SpecDirs, name: str) -> None:
    if not valid_name(name):
        raise StoreError(400, "bad name")
    f = dirs.drafts / f"{name}.yaml"
    if f.is_symlink():
        raise StoreError(409, "refusing to delete a symlink")
    if not f.is_file():
        if (dirs.examples / f"{name}.yaml").is_file():
            raise StoreError(403, "examples are read-only")
        raise StoreError(404, "no such draft")
    f.unlink()
