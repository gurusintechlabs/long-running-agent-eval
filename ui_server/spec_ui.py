"""Form-friendly schema for the spec editor (docs/ui-api-specs.md).

The structure comes from the pydantic models in ``spec/schema.py`` (types, enums, defaults, bounds, required).
Everything a human needs on top of that lives in ONE declarative table, ``FIELD_UI``, keyed by dotted field path
(``*`` stands for a list index). A field without an entry still renders: ``build_form_schema`` falls back to a
generic widget chosen from its type, and marks it ``"fallback": true``.

To add metadata for a new schema field, add one line to ``FIELD_UI``. Nothing else needs to change.
"""
from __future__ import annotations

import types
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from spec.schema import Spec

# Widgets the frontend must implement. ``json`` is the generic fallback for anything unusual.
WIDGETS = ("text", "textarea", "number", "select", "checkbox", "path", "string_list", "object", "object_list", "json")

SECTIONS = [
    {"id": "identity", "label": "Experiment", "help": "What this experiment is called."},
    {"id": "task", "label": "Task", "help": "The work the agent is given: prompt, seed repository, hidden tests."},
    {"id": "agent", "label": "Agent", "help": "Which agent runs the task, and with which model."},
    {"id": "run", "label": "Run plan", "help": "Duration, checkpoints, repeats and harness configurations."},
    {"id": "budget", "label": "Budget", "help": "Spending limits. Runs stop when a limit is reached."},
    {"id": "isolation", "label": "Isolation", "help": "Where the agent works on this machine."},
    {"id": "telemetry", "label": "Telemetry", "help": "Telemetry export settings."},
    {"id": "guardrails", "label": "Guardrails", "help": "Safety rules applied while the agent works."},
    {"id": "scoring", "label": "Scoring", "help": "Judges, thresholds, security and behaviour scoring."},
    {"id": "security", "label": "Security scoring", "help": "SAST, exploit suite and AI vulnerability review."},
    {"id": "behavior", "label": "Behaviour scoring", "help": "Passive behaviour detectors and judges."},
]

# Which section a top-level key belongs to (scoring.security / scoring.behavior get their own).
_SECTION_OF = {"spec_version": "identity", "experiment_id": "identity"}


def _f(label: str, help: str = "", **kw: Any) -> dict:
    return {"label": label, "help": help, **kw}


_PATH = {"widget": "path", "path_kind": "file", "relative_to": "spec_file"}
_DIR = {"widget": "path", "path_kind": "dir", "relative_to": "spec_file"}
_REPO_PATH = {"widget": "path", "path_kind": "file_or_dir", "relative_to": "spec_file"}
_WS_GLOB = {"widget": "string_list", "item_hint": "glob relative to the workspace, no '..', outside .git"}
_MODEL = {"widget": "text", "pattern": r"^claude-[a-z0-9][a-z0-9.\-]*$", "suggestions": ["claude-opus-5-5",
          "claude-sonnet-5-5", "claude-haiku-5-5"]}

# path -> metadata. Keys: label, help, widget, unit, advanced, section, placeholder, path_kind, relative_to,
# item_hint, pattern, suggestions, visible_if, required_if, notes.
FIELD_UI: dict[str, dict] = {
    "spec_version": _f("Spec version", "Always 1.", widget="select", advanced=True),
    "experiment_id": _f("Experiment ID", "Lower-case words joined by dashes. It is part of every run ID.",
                        placeholder="my-experiment", pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$"),

    "task": _f("Task"),
    "task.id": _f("Task ID", "Short name of the task."),
    "task.class": _f("Task class", "Difficulty class label, for example L1.", placeholder="L1"),
    "task.prompt_file": _f("Prompt file", "Markdown prompt given to the agent (stage 0 prompt when staged).", **_PATH),
    "task.seed_repo": _f("Seed repository", "Directory of the seed repository. Identified by the commit, not hashed.", **_DIR),
    "task.seed_commit": _f("Seed commit", "Full 40-character commit SHA of the seed repository.",
                           pattern=r"^[0-9a-f]{40}$", placeholder="40 hex characters"),
    "task.seed_requirements_lock": _f("Requirements lock", "Pinned requirements file of the seed.", **_PATH),
    "task.constraints_file": _f("Constraints file", "Project constraints the scorer checks (yaml).", **_PATH),
    "task.hidden_tests": _f("Hidden tests", "Hidden test suite directory. Never visible to the agent.", **_DIR),
    "task.stages_file": _f("Stages file", "Optional staged brief. Stage 0's prompt must equal the prompt file.", **_PATH),
    "task.workspace_memory": _f("Workspace memory (CLAUDE.md)", "The task's own CLAUDE.md, committed at the seed root.",
                                advanced=True, **_PATH),
    "task.permissions": _f("Permissions", "Task-owned Claude Code permission rules.", advanced=True),
    "task.permissions.deny": _f("Deny rules", "Claude Code permission rules to deny, one per line.",
                                widget="string_list", item_hint="for example Bash(rm:*)"),
    "task.protected_paths": _f("Protected paths", "Globs the agent must leave alone. Violations are logged, not blocked.",
                               advanced=True, **_WS_GLOB),
    "task.honey": _f("Decoy credentials", "Decoy credential files that detect snooping.", advanced=True),
    "task.honey.*.id": _f("Decoy ID"),
    "task.honey.*.path": _f("Decoy path", "Relative to the workspace (or to the outside area), no '..'."),
    "task.honey.*.where": _f("Placed", "Inside the workspace or outside it."),
    "task.honey.*.template": _f("Template", "File content. Must contain {TOKEN}.", widget="textarea"),
    "task.counterparts": _f("Counterparts", "Harness-run helpers that simulate other parties.", advanced=True),
    "task.counterparts.ops": _f("Ops counterpart", "Simulated operations inbox.", advanced=True),
    "task.counterparts.ops.policy_file": _f("Ops policy file", "ops_policy.yaml for the ops counterpart.", **_PATH),
    "task.counterparts.embed": _f("Embedding counterpart", "Simulated embedding service.", advanced=True),
    "task.counterparts.embed.dims": _f("Embedding dimensions", "Vector size.", unit="dims"),
    # J1 (jira-re): an external MCP server the harness registers but does not run; paths outside the repo
    "task.counterparts.rea": _f("REA counterpart", "External reverse-engineering MCP server (REA), registered in "
                                "the run's MCP config.", advanced=True),
    "task.counterparts.rea.command": _f("REA command", "The MCP server launcher; ~ is your home.", widget="text",
                                        placeholder="~/lrae-tools/re/bin/rea-mcp"),
    "task.counterparts.rea.args": _f("REA arguments", "Extra arguments for the launcher.", widget="string_list",
                                     advanced=True),
    "task.counterparts.rea.env_file": _f("REA env file", "KEY=VALUE lines passed to the server.", widget="text",
                                         placeholder="~/lrae-tools/re/rea.env"),
    "task.toolchain": _f("Toolchain", "Tools installed outside the repo (decompilers, Maven, REA); pre-flight "
                         "checks the pinned manifests.", advanced=True),
    "task.toolchain.dir": _f("Toolchain directory", "Where the install script put the tools; ~ is your home.",
                             widget="text", placeholder="~/lrae-tools/re"),
    "task.toolchain.manifest_sha256": _f("Tools manifest SHA-256", "Printed by install_re_tools.sh. Unset: not "
                                         "checked.", advanced=True, pattern=r"^[0-9a-f]{64}$"),
    "task.toolchain.m2_manifest_sha256": _f("Maven repo manifest SHA-256", "Printed by prime_maven_repo.py. Unset: "
                                            "not checked.", advanced=True, pattern=r"^[0-9a-f]{64}$"),
    "task.exploit_tests": _f("Exploit tests", "Hidden black-box exploit tests (each asserts an attack fails).",
                             advanced=True, **_DIR),

    "agent": _f("Agent"),
    "agent.runtime": _f("Runtime", "claude_code runs the installed Claude Code CLI. scripted replays a fixed script "
                        "and spends nothing.", notes=[{"level": "warning", "when": {"path": "agent.runtime",
                        "equals": "claude_code"}, "text": "claude_code runs use real subscription usage "
                        "(API-equivalent dollars). Launching asks for confirmation."}]),
    "agent.claude_bin": _f("Claude binary", "Name or path of the claude executable.", advanced=True),
    "agent.claude_code_version": _f("Claude Code version", "Must equal `claude --version` at run start.",
                                    placeholder="2.1.301"),
    "agent.model": _f("Agent model", "Full model ID. Required for claude_code, not used by scripted.",
                      required_if={"path": "agent.runtime", "equals": "claude_code"},
                      visible_if={"path": "agent.runtime", "equals": "claude_code"}, **_MODEL),
    "agent.auto_memory": _f("Auto-memory", "cli_default leaves the CLI's memory setting alone; off disables it.",
                            advanced=True),
    "agent.script": _f("Script file", "Scripted agent script. Only for the scripted runtime.",
                       required_if={"path": "agent.runtime", "equals": "scripted"},
                       visible_if={"path": "agent.runtime", "equals": "scripted"}, **_PATH),

    "run": _f("Run plan"),
    "run.duration_min": _f("Duration", "Total wall-clock length of one run.", unit="minutes"),
    "run.checkpoint_interval_min": _f("Checkpoint interval", "Must divide the duration exactly.", unit="minutes"),
    "run.repeats": _f("Repeats", "Runs per configuration."),
    "run.configs": _f("Harness configurations", "Subset of A to E. One run per configuration and repeat.",
                      widget="select", multiple=True, options=["A", "B", "C", "D", "E"]),
    "run.seed": _f("Seed", "Random seed.", advanced=True),
    "run.parallelism": _f("Parallelism", "Runs at once. The UI launches one at a time.", advanced=True),

    "budget": _f("Budget"),
    "budget.per_run_usd": _f("Cost cap per run", "Run stops when the API-equivalent estimate reaches this.", unit="USD"),
    "budget.per_run_tokens": _f("Token cap per run", "Optional.", unit="tokens", advanced=True),
    "budget.experiment_usd": _f("Cost cap for the experiment", "No new run starts once this is reached.", unit="USD"),

    "isolation": _f("Isolation"),
    "isolation.mode": _f("Mode", "local runs as a local process; docker is optional.", advanced=True),
    "isolation.work_dir": _f("Work directory", "Where the agent works. Must be outside the repository. "
                             "Not part of the spec hash.", widget="path", path_kind="dir", relative_to="absolute",
                             placeholder="~/lrae-work"),
    "isolation.keep_work_dir": _f("Keep work directory", "Keep the workspace after the run.", advanced=True),

    "telemetry": _f("Telemetry", advanced=True),
    "telemetry.protocol": _f("Protocol", advanced=True),
    "telemetry.export_interval_ms": _f("Export interval", advanced=True, unit="ms"),

    "guardrails": _f("Guardrails"),
    "guardrails.policy_file": _f("Policy file", "Guardrail rules (yaml).", **_PATH),

    "scoring": _f("Scoring"),
    "scoring.judge_model": _f("Judge model", "Full model ID used by the judges.", **_MODEL),
    "scoring.judge_samples": _f("Judge samples", "Samples per judgement.", unit="samples"),
    "scoring.judge_runtime": _f("Judge runtime", "scripted uses the deterministic fake judge (no spend).",
                                notes=[{"level": "warning", "when": {"path": "scoring.judge_runtime",
                                        "equals": "claude_code"}, "text": "Real judges spend subscription usage."}]),
    "scoring.max_commit_scoring_s": _f("Commit scoring time limit", "Above it, commits are sampled.",
                                       unit="seconds", advanced=True),
    "scoring.checkpoint_timeout_s": _f("Checkpoint scoring timeout", "Past it the pass is killed and can be re-scored.",
                                       unit="seconds", advanced=True),
    "scoring.thresholds": _f("Thresholds", advanced=True),
    "scoring.thresholds.repeat_work_ratio": _f("Repeat-work ratio", unit="ratio", advanced=True),
    "scoring.thresholds.cost_per_commit_multiplier": _f("Cost per commit multiplier", unit="x", advanced=True),
    "scoring.thresholds.cost_baseline_checkpoints": _f("Cost baseline checkpoints", unit="checkpoints", advanced=True),

    "scoring.security": _f("Security scoring", "Off unless enabled.", section="security", advanced=True),
    "scoring.security.enabled": _f("Enable security scoring", section="security", advanced=True),
    "scoring.security.semgrep_version": _f("Semgrep version", "Must match `semgrep --version`.", section="security",
                                           advanced=True),
    "scoring.security.semgrep_rules_commit": _f("Semgrep rules commit", "Full 40-character SHA of semgrep-rules.",
                                                section="security", advanced=True, pattern=r"^[0-9a-f]{40}$"),
    "scoring.security.semgrep_rulesets": _f("Semgrep rulesets", "Subdirectories of the rules repo.",
                                            section="security", advanced=True),
    "scoring.security.semgrep_pro_configs": _f("Semgrep Pro configs", "Local --pro runs; needs a pinned version; "
                                               "not reproducible.", section="security", advanced=True),
    "scoring.security.ignore": _f("Suppressions", "List of {rule, paths} suppressions owned by the scorer.",
                                  section="security", advanced=True, widget="json"),
    "scoring.security.ai_review": _f("AI vulnerability review", "One review per completed stage. Needs a context file.",
                                     section="security", advanced=True,
                                     notes=[{"level": "warning", "when": {"path": "scoring.security.ai_review",
                                             "equals": True}, "text": "Spends subscription usage per stage."}]),
    "scoring.security.ai_review_model": _f("AI review model", "Defaults to the judge model.", section="security",
                                           advanced=True, **_MODEL),
    "scoring.security.ai_review_runtime": _f("AI review runtime", section="security", advanced=True),
    "scoring.security.context_file": _f("Application context file", "Required when AI review is on.",
                                        section="security", advanced=True, **_PATH),

    "scoring.behavior": _f("Behaviour scoring", "Deterministic detectors and judges. Observe only.",
                           section="behavior", advanced=True),
    "scoring.behavior.enabled": _f("Enable behaviour scoring", section="behavior", advanced=True),
    "scoring.behavior.agent_suite": _f("Rerun the agent's own tests", section="behavior", advanced=True),
    "scoring.behavior.agent_suite_timeout_s": _f("Agent suite timeout", unit="seconds", section="behavior", advanced=True),
    "scoring.behavior.agent_suite_runner": _f("Agent suite runner", "pytest, or maven (`sh build.sh test`, surefire "
                                              "reports; needs a toolchain).", section="behavior", advanced=True),
    "scoring.clean_room": _f("Clean-room similarity", "How much a rewrite copies the scorer's own decompilation of "
                             "the original jar. Off unless enabled; needs a toolchain.", advanced=True),
    "scoring.clean_room.enabled": _f("Enable clean-room similarity", advanced=True),
    "scoring.clean_room.decompiler": _f("Reference decompiler", "Run by the scorer, outside the agent's work dir.",
                                        advanced=True),
    "scoring.clean_room.jar_glob": _f("Original jar", "Glob in the seed checkout; exactly one match.", widget="text",
                                      advanced=True),
    "scoring.clean_room.src": _f("Rewrite sources", "Workspace dirs holding the rewrite's Java.", widget="string_list",
                                 advanced=True),
    "scoring.clean_room.k": _f("k-gram length", "Tokens per fingerprinted k-gram.", unit="tokens", advanced=True),
    "scoring.clean_room.window": _f("Winnowing window", unit="k-grams", advanced=True),
    "scoring.behavior.eval_paths": _f("Eval paths", "Eval files the agent must not edit (globs).", section="behavior",
                                      advanced=True, **_WS_GLOB),
    "scoring.behavior.data_paths": _f("Data paths", "Protected data (globs).", section="behavior", advanced=True,
                                      **_WS_GLOB),
    "scoring.behavior.loop_max_period": _f("Loop max period", section="behavior", advanced=True),
    "scoring.behavior.loop_min_cycles": _f("Loop min cycles", section="behavior", advanced=True),
    "scoring.behavior.loop_hazard_cycles": _f("Loop hazard cycles", section="behavior", advanced=True),
    "scoring.behavior.stall_min_s": _f("Stall minimum", unit="seconds", section="behavior", advanced=True),
    "scoring.behavior.stall_hazard_s": _f("Stall hazard", unit="seconds", section="behavior", advanced=True),
    "scoring.behavior.spike_z": _f("Spike z-score", section="behavior", advanced=True),
    "scoring.behavior.baseline_min": _f("Baseline window", unit="minutes", section="behavior", advanced=True),
    "scoring.behavior.retry_storm_per_min": _f("Retry storm rate", unit="per minute", section="behavior", advanced=True),
    "scoring.behavior.stuck_repeats": _f("Stuck repeats", section="behavior", advanced=True),
    "scoring.behavior.scope_drift_threshold": _f("Scope drift threshold", unit="ratio", section="behavior", advanced=True),
    "scoring.behavior.stale_after_s": _f("Stale after", unit="seconds", section="behavior", advanced=True),
    "scoring.behavior.stale_patterns": _f("Stale patterns", "Regexes that are stale after an environment change.",
                                          section="behavior", advanced=True),
    "scoring.behavior.ops_inbox_each_stage": _f("Ops inbox every stage", "Rules require reading the ops inbox at the "
                                                "start of every stage.", section="behavior", advanced=True),
    "scoring.behavior.benchmark": _f("Benchmark hack gap", section="behavior", advanced=True),
    "scoring.behavior.hack_gap_threshold": _f("Hack gap threshold", unit="ratio", section="behavior", advanced=True),
    "scoring.behavior.judges": _f("Judges", "Behaviour judges that run with the judge model.", section="behavior",
                                  advanced=True, widget="select", multiple=True,
                                  options=["goal_observer", "manipulation", "prose_claims"],
                                  notes=[{"level": "warning", "when": {"path": "scoring.judge_runtime",
                                          "equals": "claude_code"}, "text": "Judges spend subscription usage."}]),
    "scoring.behavior.judge_fixtures": _f("Judge fixtures", "Recorded judge answers (canaries).", section="behavior",
                                          advanced=True, **_PATH),
}

# Notes that span several fields. ``when`` is evaluated by the frontend on the form data.
CROSS_FIELD_NOTES = [
    {"level": "warning", "paths": ["agent.runtime"], "when": {"path": "agent.runtime", "equals": "claude_code"},
     "text": "claude_code runtime spends real money (API-equivalent estimate against the subscription)."},
    {"level": "info", "paths": ["run.duration_min", "run.checkpoint_interval_min"],
     "text": "checkpoint_interval_min must divide duration_min exactly."},
    {"level": "info", "paths": ["agent.runtime", "agent.script", "agent.model"],
     "text": "scripted needs agent.script and no model; claude_code needs agent.model and no script."},
    {"level": "info", "paths": ["scoring.security.ai_review", "scoring.security.context_file"],
     "text": "AI review needs a context file."},
    {"level": "info", "paths": ["scoring.security.semgrep_pro_configs", "scoring.security.semgrep_version"],
     "text": "Semgrep Pro configs need a pinned semgrep_version."},
]


# --- schema walking -------------------------------------------------------------------------------

def _unwrap(ann: Any) -> tuple[Any, bool]:
    """(annotation without None, nullable)."""
    if get_origin(ann) in (Union, types.UnionType):
        args = [a for a in get_args(ann) if a is not type(None)]
        nullable = len(args) != len(get_args(ann))
        if len(args) == 1:
            return args[0], nullable
        return Union[tuple(args)], nullable  # noqa: UP007
    return ann, False


def _is_model(t: Any) -> bool:
    return isinstance(t, type) and issubclass(t, BaseModel)


def _constraints(fi) -> dict:
    out: dict[str, Any] = {}
    for m in fi.metadata:
        for attr, key in (("gt", "exclusive_min"), ("ge", "min"), ("lt", "exclusive_max"), ("le", "max"),
                          ("min_length", "min_items")):
            if hasattr(m, attr) and getattr(m, attr) is not None:
                out[key] = getattr(m, attr)
    return out


def _default(fi) -> Any:
    if fi.default is not PydanticUndefined:
        d = fi.default
    elif fi.default_factory is not None:
        d = fi.default_factory()
    else:
        return None
    if isinstance(d, BaseModel):
        return d.model_dump(mode="json", by_alias=True)
    if isinstance(d, list):
        return [x.model_dump(mode="json", by_alias=True) if isinstance(x, BaseModel) else x for x in d]
    return d


def _entry(path: str, key: str, fi, parent_section: str) -> dict:
    ann, nullable = _unwrap(fi.annotation)
    origin = get_origin(ann)
    e: dict[str, Any] = {"path": path, "key": key, "required": fi.is_required(), "nullable": nullable,
                         "default": _default(fi), **_constraints(fi)}
    children: dict | None = None
    if _is_model(ann):
        e.update(kind="object", widget="object")
        children = {"model": ann}
    elif origin is list:
        item, _ = _unwrap(get_args(ann)[0] if get_args(ann) else Any)
        if _is_model(item):
            e.update(kind="list", item_kind="object", widget="object_list")
            children = {"model": item, "path": path + ".*"}
        elif item is str:
            e.update(kind="list", item_kind="string", widget="string_list")
        else:
            e.update(kind="list", item_kind="json", widget="json")
    elif origin is Literal:
        e.update(kind="enum", widget="select", options=list(get_args(ann)))
    elif ann is bool:
        e.update(kind="boolean", widget="checkbox")
    elif ann is int:
        e.update(kind="integer", widget="number")
    elif ann is float:
        e.update(kind="number", widget="number")
    elif ann is str:
        e.update(kind="string", widget="text")
    else:
        e.update(kind="json", widget="json")
    meta = FIELD_UI.get(path)
    e["fallback"] = meta is None
    if meta:
        e.update({k: v for k, v in meta.items() if k not in ("label", "help")})
    e["label"] = (meta or {}).get("label") or key.replace("_", " ").capitalize()
    e["help"] = (meta or {}).get("help", "")
    if e["widget"] not in WIDGETS:
        e["widget"] = "json"
    top = path.split(".")[0]
    e.setdefault("section", parent_section or _SECTION_OF.get(top, top))
    e.setdefault("advanced", False)
    if children:
        sub = []
        base = children.get("path", path)
        for ck, cfi in children["model"].model_fields.items():
            ckey = cfi.alias or ck
            sub.append(_entry(f"{base}.{ckey}", ckey, cfi, e["section"]))
        e["fields"] = sub
    return e


def build_form_schema() -> dict:
    """The whole payload of ``GET /api/specs/schema``."""
    fields = []
    for name, fi in Spec.model_fields.items():
        fields.append(_entry(fi.alias or name, fi.alias or name, fi, ""))
    return {
        "version": 1,
        "widgets": list(WIDGETS),
        "sections": SECTIONS,
        "fields": fields,
        "cross_field_notes": CROSS_FIELD_NOTES,
        "json_schema": Spec.model_json_schema(by_alias=True),
    }


def iter_fields(fields: list[dict]):
    """Depth-first walk over a ``fields`` tree."""
    for f in fields:
        yield f
        yield from iter_fields(f.get("fields", []))

