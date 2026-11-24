"""jira-re JC1: analyst/build_claims.py writes spec/claims.jsonl and analyst/claims-evidence.jsonl from the
analyst's claim notes, with permanent ids (docs/jira-re-design.md §7.2, design: ids are never reused)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TASK = Path(__file__).resolve().parents[2] / "fixtures" / "tasks" / "jira_re"
sys.path.insert(0, str(TASK / "analyst"))
sys.path.insert(0, str(TASK / "hidden"))

import build_claims as bc  # noqa: E402

MODULES = {"gate", "engine"}
API = {"com.acme.api.Ids", "com.acme.api.Store"}
CLASSES = {"com.acme.Gate", "com.acme.internal.RuleEngine", "com.acme.api.Ids"}


def _resolve(ref: str) -> bool:
    return ref.split("#", 1)[0] in CLASSES


def _claim(key: str, **kw) -> dict:
    c = {"key": key, "module": "gate", "behaviour": f"When {key}, then y.", "confidence": "high",
         "evidence": ["com.acme.Gate"]}
    c.update(kw)
    return {k: v for k, v in c.items() if v is not ...}


def _build(claims: list[dict], ids: dict | None = None, **kw):
    args = dict(modules=MODULES, api_types=API, resolve=_resolve,
                internal={"com.acme.internal.RuleEngine", "com.acme.internal.AOBasedStore", "app/ui/GridPresenter"},
                internal_simple={"RuleEngine", "AOBasedStore"}, allowed=set())
    args.update(kw)
    return bc.build(claims, dict(ids or {}), **args)


def _rows(text: str) -> list[dict]:
    return [json.loads(ln) for ln in text.splitlines()]


def test_claims_get_ids_in_order_and_the_implementer_copy_has_no_keys_or_evidence():
    out = _build([_claim("a"), _claim("b", module=None, api="com.acme.api.Ids", evidence=["com.acme.api.Ids#of"],
                                      confidence="medium")])
    assert out.ids == {"a": "C-0001", "b": "C-0002"}
    assert _rows(out.claims) == [
        {"id": "C-0001", "module": "gate", "behaviour": "When a, then y.", "confidence": "high", "status": "active"},
        {"id": "C-0002", "module": None, "api": "com.acme.api.Ids", "behaviour": "When b, then y.",
         "confidence": "medium", "status": "active"}]
    assert _rows(out.evidence) == [{"id": "C-0001", "key": "a", "evidence": ["com.acme.Gate"]},
                                   {"id": "C-0002", "key": "b", "evidence": ["com.acme.api.Ids#of"]}]


def test_ids_are_permanent_new_claims_get_the_next_free_id():
    first = _build([_claim("a"), _claim("b")])
    again = _build([_claim("c"), _claim("b"), _claim("a")], first.ids)    # notes reordered, one added
    assert again.ids == {"a": "C-0001", "b": "C-0002", "c": "C-0003"}
    assert [r["id"] for r in _rows(again.claims)] == ["C-0001", "C-0002", "C-0003"]   # sorted by id


def test_suspected_bugs_are_flagged_for_the_implementer():
    """JC2 (owner): a claim the analyst marks "(as the original does)" states a suspected bug of the original;
    the implementer's copy flags it, so it is checked during implementation. Other claims carry no flag."""
    rows = _rows(_build([_claim("bug", behaviour="It returns null (as the original does)."),
                         _claim("bug2", behaviour="It keeps 501 rows (one more than the limit, As the original does)."),
                         _claim("plain")]).claims)
    assert [r.get("suspected_bug") for r in rows] == [True, True, None]
    assert list(rows[0]) == ["id", "module", "behaviour", "confidence", "status", "suspected_bug"]


def test_a_claim_is_retracted_never_dropped():
    first = _build([_claim("a"), _claim("b")])
    with pytest.raises(ValueError, match=r"C-0001 \(a\) was dropped"):
        _build([_claim("b")], first.ids)
    out = _build([_claim("a", status="retracted"), _claim("b"), _claim("c")], first.ids)
    assert [(r["id"], r["status"]) for r in _rows(out.claims)] == [
        ("C-0001", "retracted"), ("C-0002", "active"), ("C-0003", "active")]


@pytest.mark.parametrize("bad, message", [
    (_claim("x", behaviour=" "), "x: behaviour must be non-empty"),
    (_claim("x", confidence="sure"), "x: confidence must be one of"),
    (_claim("x", status="gone"), "x: status must be one of"),
    (_claim("x", module="nope"), "x: module 'nope' is not in the original descriptor"),
    (_claim("x", module=None, api="com.acme.api.Nope"), "x: API type 'com.acme.api.Nope' is not"),
    (_claim("x", api="com.acme.api.Ids"), "x: names both a module and an API type"),
    (_claim("x", module=None), "x: names neither a module nor an API type"),
    (_claim("x", evidence=[]), "x: no evidence"),
    (_claim("x", evidence=["com.acme.Nope#run"]), "x: evidence com.acme.Nope#run is not in the jar"),
    (_claim("x", behaviour="It calls com.acme.internal.RuleEngine."), "x: names internal class com.acme.internal.RuleEngine"),
    (_claim("x", behaviour="The RuleEngine decides."), "x: names internal class RuleEngine"),
    # a name that starts with an acronym, inside a key whose package is not the class's own (JC2)
    (_claim("x", behaviour="Key `com.acme.old.AOBasedStore.limit` sets it."), "x: names internal class AOBasedStore"),
    (_claim("x", behaviour="The module app/ui/GridPresenter decides."), "x: names internal class app/ui/GridPresenter"),
    (_claim("x", colour="red"), "x: unknown field colour"),
    ({"module": "gate", "behaviour": "b", "confidence": "high", "evidence": ["com.acme.Gate"]}, "claim without a key"),
])
def test_bad_claims_fail_the_build(bad, message):
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)").replace(".", r"\.")):
        _build([_claim("ok"), bad])


def test_allowed_names_and_duplicate_keys():
    out = _build([_claim("x", behaviour="It persists com.acme.internal.RuleEngine.")],
                 allowed={"com.acme.internal.RuleEngine"})
    assert "RuleEngine" in out.claims
    with pytest.raises(ValueError, match="key 'a' is used twice"):
        _build([_claim("a"), _claim("a")])


def test_notes_files_merge_in_name_order(tmp_path):
    (tmp_path / "b.json").write_text(json.dumps({"claims": [_claim("b1")]}))
    (tmp_path / "a.json").write_text(json.dumps({"claims": [_claim("a1"), _claim("a2")]}))
    claims = bc.load_notes(tmp_path)
    assert [c["key"] for c in claims] == ["a1", "a2", "b1"]
    assert _build(claims).ids == {"a1": "C-0001", "a2": "C-0002", "b1": "C-0003"}


def test_the_build_is_deterministic():
    one = _build([_claim("a"), _claim("b")])
    two = _build([_claim("a"), _claim("b")], one.ids)
    assert (one.claims, one.evidence, one.ids) == (two.claims, two.evidence, two.ids)
    assert one.claims.endswith("\n") and one.evidence.endswith("\n")


def test_notes_map_api_tests_to_claims_by_key(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"claims": [_claim("a"), _claim("b")],
                                                 "tests": {"t.ATest#one": ["b", "a"]}}))
    (tmp_path / "b.json").write_text(json.dumps({"claims": [_claim("c")], "tests": {"t.BTest#two": ["c"]}}))
    claims, tests = bc.load_notes(tmp_path), bc.load_tests(tmp_path)
    out = _build(claims, tests=tests)
    assert json.loads(out.tests) == {"t.ATest#one": ["C-0001", "C-0002"], "t.BTest#two": ["C-0003"]}
    with pytest.raises(ValueError, match="t.ATest#one cites unknown claim key 'zz'"):
        _build(claims, tests={"t.ATest#one": ["zz"]})
    (tmp_path / "c.json").write_text(json.dumps({"tests": {"t.BTest#two": ["a"]}}))
    with pytest.raises(ValueError, match="t.BTest#two is mapped in two notes files"):
        bc.load_tests(tmp_path)
