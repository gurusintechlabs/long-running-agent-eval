"""Staged task briefs (docs/interfaces.md §9, decisions D-18 and D-18a).

A staged task gives the agent its brief in parts: stage 0 at the start, then each next stage as soon
as the agent finishes the current one, i.e. as soon as its ``claude -p`` turn ends successfully.
Later stages add features or overturn earlier behaviour (change requests), so the agent has to
revise its own work deep into a long session. There is no clock: nothing waits, and the run ends
when the agent finishes the last stage (or at ``run.duration_min``, whichever comes first).

D-18a (docs/behavior-design.md §5.1) adds optional per-stage fields, all identical across configs:

* ``kind``: also ``directive``, ``environment``, ``incident``, ``inbound`` and ``release``.
* ``source``: who sends the message (``product_owner`` | ``ops``). When set, the message starts
  with a ``From:`` header; when absent the text is sent unchanged (v1/v2 tasks).
* ``surface``: globs of the files the stage is expected to touch (goal-drift detector).
* ``directives``: machine-readable ``{freeze: [globs]}`` or ``{stop: "<item>"}`` orders, optionally
  lifted when stage ``until_stage`` is delivered (command-evasion detector).
* ``env_actions``: changes the harness makes right before the stage is delivered
  (``runner/envmut.py``): a doc committed by "platform-bot", a counterpart service switched to a new
  mode, a fixture process started or stopped.
* ``status_block: required``: the stage must end with a STATUS block (claim audit).
* ``authorizes``: workspace globs of protected data the stage authorises the agent to change, from its
  delivery on (an approved migration, say). By default nothing is: protected data stays protected
  for the whole run (exploratory-damage detector).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

KINDS = ("feature", "change_request", "directive", "environment", "incident", "inbound", "release")
SOURCES = {"product_owner": "product owner", "ops": "ops channel"}
STAGE_KEYS = {"id", "prompt", "kind", "source", "surface", "directives", "env_actions", "status_block",
              "authorizes"}
# Every env action the schema knows, with its required and optional parameters. Only the ones in
# IMPLEMENTED_ACTIONS can be used today; the rest arrive with the counterpart services (plan B3).
ENV_ACTIONS = {
    "commit_file": ({"path", "from", "author"}, {"message"}),
    "counterpart_mode": ({"service", "mode"}, set()),
    "start_process": ({"name", "fixture"}, {"params"}),
    "stop_process": ({"name"}, set()),
}
IMPLEMENTED_ACTIONS = set(ENV_ACTIONS)
SERVICES = ("embed",)                          # counterpart services a stage can switch (plan B3)
FIXTURES = ("lock_holder", "port_holder")      # runner/counterparts/fixtures.py
AUTHOR_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


class StageError(ValueError):
    pass


@dataclass(frozen=True)
class Directive:
    id: str                          # "s<stage>-d<index>"
    stage: int                       # issued when this stage is delivered
    freeze: tuple[str, ...] = ()     # globs that must not change while the directive is in force
    stop: str | None = None          # a work item the agent must stop working on
    until_stage: int | None = None   # lifted when this stage is delivered (None: never)
    # regexes over source text: a non-test .py file that matches one (defines index code, say) is frozen
    # too, wherever the agent put it ("if your index code lives elsewhere, the directive covers it too")
    freeze_defining: tuple[str, ...] = ()

    def as_payload(self) -> dict:
        out: dict = {"id": self.id, "stage": self.stage, "until_stage": self.until_stage}
        if self.freeze:
            out["freeze"] = list(self.freeze)
        if self.freeze_defining:
            out["freeze_defining"] = list(self.freeze_defining)
        if self.stop is not None:
            out["stop"] = self.stop
        return out


@dataclass(frozen=True)
class EnvAction:
    action: str
    params: dict
    source_file: Path | None = None  # resolved ``from`` file (commit_file), hashed into spec_hash


@dataclass(frozen=True)
class Stage:
    id: int
    prompt: Path
    kind: str = "feature"
    source: str | None = None
    surface: tuple[str, ...] = ()
    directives: tuple[Directive, ...] = ()
    env_actions: tuple[EnvAction, ...] = ()
    status_block: bool = False
    authorizes: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return self.prompt.read_text()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.prompt.read_bytes()).hexdigest()

    def message(self, body: str | None = None) -> str:
        """What the agent receives: ``body`` (default: the prompt text) with a ``From:`` header when
        the stage declares its source."""
        body = self.text if body is None else body
        if self.source is None:
            return body
        return f"From: {SOURCES[self.source]}\n\n{body}"


@dataclass(frozen=True)
class StagePlan:
    stages: list[Stage]
    referenced_files: list[Path] = field(default_factory=list)  # env action sources, for spec_hash

    def directives_issued_at(self, stage_id: int) -> list[Directive]:
        return list(self.stages[stage_id].directives) if 0 <= stage_id < len(self.stages) else []

    def directives_lifted_at(self, stage_id: int) -> list[Directive]:
        return [d for s in self.stages for d in s.directives if d.until_stage == stage_id]

    def authorized_through(self, stage_id: int | None) -> list[str]:
        """Globs of protected data authorised by the stages delivered up to ``stage_id`` (None: none)."""
        if stage_id is None:
            return []
        return [g for s in self.stages if s.id <= stage_id for g in s.authorizes]

    def fixture_paths(self) -> list[str]:
        """Workspace files that ``start_process`` fixtures hold (a lock holder's ``params.path``): the harness
        writes them, so the protected-path guardrail does not report them as the agent's."""
        return sorted({a.params["params"]["path"] for s in self.stages for a in s.env_actions
                       if a.action == "start_process" and "path" in (a.params.get("params") or {})})


def _authorizes(s: dict, i: int) -> tuple[str, ...]:
    if "authorizes" not in s:
        return ()
    globs = _str_list(s["authorizes"], f"stage {i} authorizes")
    if not globs or any(g.startswith("/") or ".." in PurePosixPath(g).parts for g in globs):
        raise StageError(f"stage {i}: authorizes needs workspace-relative globs, got {s['authorizes']!r}")
    return globs


def _str_list(value, what: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        raise StageError(f"{what}: expected a list of non-empty strings, got {value!r}")
    return tuple(value)


def _directives(raw, stage_id: int, n_stages: int) -> tuple[Directive, ...]:
    if not isinstance(raw, list):
        raise StageError(f"stage {stage_id}: directives must be a list")
    out = []
    for i, d in enumerate(raw):
        where = f"stage {stage_id} directive {i}"
        if not isinstance(d, dict) or set(d) - {"freeze", "freeze_defining", "stop", "until_stage"}:
            raise StageError(f"{where}: expected {{freeze[, freeze_defining]|stop[, until_stage]}}, got {d!r}")
        if ("freeze" in d) == ("stop" in d):
            raise StageError(f"{where}: exactly one of freeze or stop")
        until = d.get("until_stage")
        if until is not None and (not isinstance(until, int) or not stage_id < until < n_stages):
            raise StageError(f"{where}: until_stage must be a later stage id, got {until!r}")
        freeze = _str_list(d["freeze"], f"{where} freeze") if "freeze" in d else ()
        if "freeze" in d and not freeze:
            raise StageError(f"{where}: freeze needs at least one glob")
        stop = d.get("stop")
        if "stop" in d and (not isinstance(stop, str) or not stop.strip()):
            raise StageError(f"{where}: stop must be a non-empty string")
        defining = ()
        if "freeze_defining" in d:
            defining = _str_list(d["freeze_defining"], f"{where} freeze_defining")
            if not freeze or not defining:
                raise StageError(f"{where}: freeze_defining needs a freeze and at least one regex")
            for rx in defining:
                try:
                    re.compile(rx, re.M)
                except re.error as exc:
                    raise StageError(f"{where}: freeze_defining {rx!r}: {exc}") from None
        out.append(Directive(f"s{stage_id}-d{i}", stage_id, freeze, stop, until, defining))
    return tuple(out)


def _workspace_rel(path, where: str) -> str:
    p = PurePosixPath(path) if isinstance(path, str) else None
    if p is None or not str(p) or p.is_absolute() or ".." in p.parts or p.parts[:1] == (".git",):
        raise StageError(f"{where}: path must be relative to the workspace, outside .git, got {path!r}")
    return p.as_posix()


def _env_actions(raw, stage_id: int, base: Path) -> tuple[EnvAction, ...]:
    if not isinstance(raw, list):
        raise StageError(f"stage {stage_id}: env_actions must be a list")
    out = []
    for i, a in enumerate(raw):
        where = f"stage {stage_id} env action {i}"
        name = a.get("action") if isinstance(a, dict) else None
        if name not in ENV_ACTIONS:
            raise StageError(f"{where}: unknown action {name!r}")
        if name not in IMPLEMENTED_ACTIONS:
            raise StageError(f"{where}: action {name!r} is not implemented yet (counterparts, plan B3)")
        required, optional = ENV_ACTIONS[name]
        params = {k: v for k, v in a.items() if k != "action"}
        if required - set(params) or set(params) - required - optional:
            raise StageError(f"{where} ({name}): needs {sorted(required)}, may have {sorted(optional)}")
        src = None
        if name == "commit_file":
            params["path"] = _workspace_rel(params["path"], where)
            if not isinstance(params["author"], str) or not AUTHOR_RE.match(params["author"]):
                raise StageError(f"{where}: author must be a short lowercase name like platform-bot")
            src = (base / str(params["from"])).resolve()
            if not src.is_file():
                raise StageError(f"{where}: 'from' file not found: {src}")
        elif name == "counterpart_mode":
            if params["service"] not in SERVICES or not isinstance(params["mode"], dict) or not params["mode"]:
                raise StageError(f"{where}: service must be one of {SERVICES} and mode a non-empty mapping")
        elif name in ("start_process", "stop_process"):
            if not isinstance(params["name"], str) or not AUTHOR_RE.match(params["name"]):
                raise StageError(f"{where}: name must be a short lowercase name like backup-daemon")
            if name == "start_process" and (params["fixture"] not in FIXTURES
                                            or not isinstance(params.get("params", {}), dict)):
                raise StageError(f"{where}: fixture must be one of {FIXTURES}, params a mapping")
        out.append(EnvAction(name, params, src))
    return tuple(out)


def load_stages(path: Path | str) -> StagePlan:
    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise StageError(f"cannot read {path}: {exc}") from exc
    unknown = set(doc) - {"stages"}
    if unknown:
        raise StageError(f"unknown keys {sorted(unknown)}")
    raw_stages = doc.get("stages") or []
    if not raw_stages:
        raise StageError("no stages")
    n = len(raw_stages)
    stages = []
    for i, s in enumerate(raw_stages):
        if not isinstance(s, dict) or "prompt" not in s or set(s) - STAGE_KEYS:
            raise StageError(f"stage {i}: expected {{id, prompt[, {', '.join(sorted(STAGE_KEYS - {'id', 'prompt'}))}]}}, "
                             f"got {s!r}")
        prompt = (path.parent / s["prompt"]).resolve()
        if not prompt.is_file():
            raise StageError(f"stage {i}: prompt file not found: {prompt}")
        sid = int(s["id"]) if isinstance(s.get("id"), int) else i
        kind = s.get("kind", "feature")
        if kind not in KINDS:
            raise StageError(f"stage {i}: kind must be one of {', '.join(KINDS)}")
        source = s.get("source")
        if source is not None and source not in SOURCES:
            raise StageError(f"stage {i}: source must be one of {', '.join(SOURCES)}")
        status = s.get("status_block")
        if status not in (None, "required"):
            raise StageError(f"stage {i}: status_block must be 'required' when given")
        stages.append(Stage(
            id=int(s["id"]), prompt=prompt, kind=kind, source=source,
            surface=_str_list(s["surface"], f"stage {i} surface") if "surface" in s else (),
            directives=_directives(s.get("directives", []), sid, n),
            env_actions=_env_actions(s.get("env_actions", []), sid, path.parent),
            status_block=status == "required", authorizes=_authorizes(s, i)))
    if [s.id for s in stages] != list(range(len(stages))):
        raise StageError("stage ids must be 0, 1, 2, ... in order")
    refs = [a.source_file for s in stages for a in s.env_actions if a.source_file is not None]
    return StagePlan(stages, refs)


def replay_actions(plan: StagePlan, delivered: set[int]) -> list[tuple[int, EnvAction]]:
    """Env actions to replay on resume, in delivery order. The restored snapshot already holds the
    workspace with every harness commit, so ``commit_file`` is skipped; counterpart modes and
    fixtures live outside the snapshot and must be rebuilt (plan B3 follow-up)."""
    return [(s.id, a) for s in plan.stages if s.id in delivered for a in s.env_actions
            if a.action != "commit_file"]


class StageScheduler:
    """Hands out the stages in order. Delivered stages are remembered (and restored on resume)."""

    def __init__(self, plan: StagePlan, delivered: set[int] | None = None):
        self.plan = plan
        self.delivered: set[int] = set(delivered or {0})

    def next(self) -> Stage | None:
        """The next undelivered stage, or None when every stage has been delivered."""
        return next((s for s in self.plan.stages if s.id not in self.delivered), None)

    def mark_delivered(self, stage: Stage) -> None:
        self.delivered.add(stage.id)

    def active(self) -> int:
        return max(self.delivered)
