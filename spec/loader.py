"""Load, validate and hash an experiment spec (docs/spec.md §4.1, §4.2)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from spec.schema import HarnessConfig, Spec

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = Path(__file__).resolve().parent / "configs"

# Spec fields that hold paths to referenced files/dirs; hashed by content, not by location.
_PATH_FIELDS = [
    ("task", "prompt_file"),
    ("task", "constraints_file"),
    ("task", "hidden_tests"),
    ("task", "seed_requirements_lock"),
    ("guardrails", "policy_file"),
    ("agent", "script"),
    ("task", "stages_file"),
    ("task", "workspace_memory"),
    ("task", "exploit_tests"),
]


class SpecError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_path(path: Path) -> str:
    """Content hash of a file, or of a directory tree (sorted relative names + contents)."""
    if path.is_file():
        return sha256_bytes(path.read_bytes())
    if path.is_dir():
        h = hashlib.sha256()
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            if "__pycache__" in f.parts or f.suffix == ".pyc":
                continue
            h.update(f.relative_to(path).as_posix().encode())
            h.update(b"\0")
            h.update(f.read_bytes())
            h.update(b"\0")
        return h.hexdigest()
    raise SpecError(f"referenced path does not exist: {path}")


@dataclass(frozen=True)
class LoadedSpec:
    spec: Spec
    spec_hash: str
    path: Path

    def run_id(self, config: str, repeat: int) -> str:
        return f"{self.spec.experiment_id}-{config}-r{repeat:02d}-{self.spec_hash[:8]}"


def load_harness_config(name: str, configs_dir: Path = CONFIGS_DIR) -> HarnessConfig:
    path = configs_dir / f"{name}.yaml"
    if not path.is_file():
        raise SpecError(f"config {name} has no file at {path}")
    try:
        return HarnessConfig.model_validate(yaml.safe_load(path.read_text()))
    except ValidationError as exc:
        raise SpecError(f"invalid config {path}: {exc}") from exc


def _resolve(spec_dir: Path, value: str) -> str:
    p = Path(value).expanduser()
    return str(p if p.is_absolute() else (spec_dir / p).resolve())


def compute_spec_hash(spec: Spec, extra_files: dict[str, Path] | None = None) -> str:
    data = spec.model_dump(mode="json", by_alias=True)
    data["isolation"].pop("work_dir")  # machine-local
    for section, field in _PATH_FIELDS:
        value = data[section][field]
        if value is not None:
            data[section][field] = {"sha256": hash_path(Path(value))}
    data["task"].pop("seed_repo")  # identified by seed_commit
    # Behaviour-track fields (D-15a, D-18a) are left out while unset, so the hash (and run ids) of
    # every spec written before them stays the same.
    if data["task"].get("workspace_memory") is None:
        data["task"].pop("workspace_memory", None)
    if not spec.task.permissions.deny:
        data["task"].pop("permissions", None)
    for key in ("protected_paths", "honey"):
        if not data["task"].get(key):
            data["task"].pop(key, None)
    if data["task"].get("exploit_tests") is None:
        data["task"].pop("exploit_tests", None)
    from spec.schema import BehaviorScoring, SecurityScoring
    if data["scoring"].get("behavior") == BehaviorScoring().model_dump(mode="json"):
        data["scoring"].pop("behavior", None)
    sec = data["scoring"].get("security")
    if sec == SecurityScoring().model_dump(mode="json"):
        data["scoring"].pop("security", None)
    elif sec and sec.get("context_file"):
        sec["context_file"] = {"sha256": hash_path(Path(sec["context_file"]))}
    cps = data["task"].get("counterparts") or {}
    if not any(cps.values()):
        data["task"].pop("counterparts", None)
    elif cps.get("ops"):
        cps["ops"]["policy_file"] = {"sha256": hash_path(Path(cps["ops"]["policy_file"]))}
    if spec.task.stages_file:  # the stage prompts are part of the task, not just the index file
        from runner.stages import load_stages
        plan = load_stages(spec.task.stages_file)
        data["task"]["stages_prompts"] = [hash_path(s.prompt) for s in plan.stages]
        if plan.referenced_files:  # files the harness puts into the workspace (env actions)
            data["task"]["stages_env_files"] = [hash_path(f) for f in plan.referenced_files]
    if extra_files:
        data["_extra_files"] = {k: hash_path(p) for k, p in sorted(extra_files.items())}
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(canonical.encode())


def load_spec(path: Path | str, repo_root: Path = REPO_ROOT) -> LoadedSpec:
    path = Path(path).resolve()
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise SpecError(f"cannot read spec {path}: {exc}") from exc
    try:
        spec = Spec.model_validate(raw)
    except ValidationError as exc:
        raise SpecError(str(exc)) from exc

    spec_dir = path.parent
    for section, field in _PATH_FIELDS + [("task", "seed_repo")]:
        obj = getattr(spec, section)
        value = getattr(obj, field)
        if value is not None:
            setattr(obj, field, _resolve(spec_dir, value))
    spec.isolation.work_dir = str(Path(spec.isolation.work_dir).expanduser().resolve())

    work = Path(spec.isolation.work_dir)
    repo = Path(repo_root).resolve()
    if work == repo or repo in work.parents:
        raise SpecError(f"isolation.work_dir must be outside the repo ({repo}); got {work}")

    for section, field in _PATH_FIELDS:
        value = getattr(getattr(spec, section), field)
        if value is not None and not Path(value).exists():
            raise SpecError(f"{section}.{field}: file does not exist: {value}")

    sec = spec.scoring.security
    if sec.context_file:
        sec.context_file = _resolve(spec_dir, sec.context_file)
        if not Path(sec.context_file).is_file():
            raise SpecError(f"scoring.security.context_file: file does not exist: {sec.context_file}")

    ops = spec.task.counterparts.ops
    if ops is not None:
        ops.policy_file = _resolve(spec_dir, ops.policy_file)
        from runner.counterparts.ops import OpsPolicy, PolicyError
        try:
            OpsPolicy.load(ops.policy_file)
        except PolicyError as exc:
            raise SpecError(f"task.counterparts.ops: {exc}") from exc

    if spec.task.stages_file:
        from runner.stages import StageError, load_stages
        try:
            plan = load_stages(spec.task.stages_file)
        except StageError as exc:
            raise SpecError(f"task.stages_file: {exc}") from exc
        if plan.stages[0].prompt.resolve() != Path(spec.task.prompt_file).resolve():
            raise SpecError("task.prompt_file must be the stage-0 prompt of task.stages_file")

    extra = {}
    review_prompt = repo / "scorer" / "vuln_review_prompt.md"
    if spec.scoring.security.enabled and spec.scoring.security.ai_review and review_prompt.is_file():
        extra["vuln_review_prompt"] = review_prompt  # plan B4: hashed only when the review is used
    for name, candidate in (
        ("judge_prompt", repo / "scorer" / "judge_prompt.md"),
        ("harness_settings", repo / "runner" / "harness_settings.template.json"),
    ):
        if candidate.is_file():
            extra[name] = candidate
    return LoadedSpec(spec=spec, spec_hash=compute_spec_hash(spec, extra), path=path)
