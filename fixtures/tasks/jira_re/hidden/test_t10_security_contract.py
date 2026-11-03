"""t10 (from stage 1): the rewrite is never more open than the original, item by item (``_security``).

REST endpoints, webwork actions and servlet filters of the original, judged where the rewrite declares the same
item and its module is in the run's scope: a dropped XSRF check, websudo requirement or filter pattern, or an
added anonymous marker, fails; an item the rewrite does not have yet is skipped. Owner 2026-11-02: the closest
jira-re gets to minidb's exploit suite until the plugin runs in a real Jira. A check that disappears after it was
there is a regression in R(t)."""
import functools
import xml.etree.ElementTree as ET

import pytest

import _api
import _security as sec
from _support import WS, VENDOR, ArtefactError, _expand, _pom_props, current_stage, scope_keys, stage, target_jar


def _jira() -> str | None:
    """The pinned Jira version (``<restrict>`` ranges), from the workspace pom; ``pom_pinned`` guards it."""
    pom = WS / "pom.xml"
    return _pom_props(pom).get("jira.version") if pom.is_file() else None


@functools.lru_cache(maxsize=1)
def reference() -> sec.Reference:
    jar = target_jar()
    if jar is None:
        return sec.Reference({}, {}, {})
    return sec.original(jar, sorted((VENDOR / "lib").glob("*.jar")), _jira())


def _ids() -> list[str]:
    return reference().ids() or [sec.NONE]


@functools.lru_cache(maxsize=1)
def rewrite() -> sec.Reference:
    path = WS / "src" / "main" / "resources" / "atlassian-plugin.xml"
    if not path.is_file():
        raise ArtefactError("src/main/resources/atlassian-plugin.xml is missing")
    try:
        root = ET.fromstring(path.read_text())
    except ET.ParseError as exc:
        raise ArtefactError(f"atlassian-plugin.xml does not parse: {exc}") from exc
    props = _pom_props(WS / "pom.xml")
    jira = _jira()
    flt = sec.filters(root, jira, expand=lambda v: _expand(v, props))
    b = _api.session_build(current_stage() >= _api.BEHAVIOUR_STAGE)   # shared with t05: one build per run
    if not b.ok:
        return sec.Reference(None, None, flt)   # classes unknown: only the descriptor items can be judged
    return sec.Reference(sec.endpoints(root, b.classes, jira), sec.actions(root, b.classes, jira), flt)


def _rewrite_part(kind: str):
    got = getattr(rewrite(), kind)
    if got is None:
        why = _api.session_build(current_stage() >= _api.BEHAVIOUR_STAGE).reason or ""
        if why.startswith("no toolchain"):   # the environment's fault, not the rewrite's (scorer.yaml sets it)
            pytest.skip(why)
        pytest.fail(f"the rewrite does not build, so its {kind} cannot be checked: {why}")
    return got


@stage(1)
@pytest.mark.parametrize("item", _ids())
def test_not_more_open_than_the_original(item):
    if item == sec.NONE:
        pytest.skip("the original declares no REST endpoint, webwork action or servlet filter")
    ref = reference()
    if ref.module_of(item) not in scope_keys():
        pytest.skip(f"{item} belongs to module {ref.module_of(item)!r}, outside this run's scope (hidden/pilot.json)")
    kind, _, name = item.partition(":")
    if kind == "rest":
        got = _rewrite_part("endpoints").get(item)
        want = ref.endpoints[item]
        problems = sec.endpoint_problems(want, got) if got else None
    elif kind == "action":
        got = _rewrite_part("actions").get(name)
        problems = sec.action_problems(ref.actions[name], got) if got else None
    else:
        got = rewrite().filters.get(name)
        problems = sec.filter_problems(ref.filters[name], got) if got else None
    if problems is None:
        pytest.skip(f"the rewrite does not declare {item} yet")
    assert not problems, f"{item}: " + "; ".join(problems)


@stage(1)
def test_no_anonymous_endpoint_beyond_the_original():
    ref = reference()
    extra = sorted(i for i, e in _rewrite_part("endpoints").items() if i not in ref.endpoints and e.anonymous)
    assert not extra, f"{len(extra)} endpoint(s) the original does not have are open to anonymous callers: {extra[:20]}"
