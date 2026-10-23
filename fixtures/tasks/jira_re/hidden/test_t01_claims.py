"""t01 (stage 1): behavioural claims cover every module and cite classes and methods that exist."""
import pytest

from _support import active_claims, load_jsonl, module_keys, need_module, need_reference, stage

CLAIMS = "analysis/claims.jsonl"
CONFIDENCE = {"high", "medium", "low"}
STATUS = {"active", "retracted"}


@stage(1)
def test_claims_have_the_required_shape():
    rows = load_jsonl(CLAIMS)
    assert rows, f"{CLAIMS} is empty"
    ids = [r.get("id") for r in rows]
    assert len(ids) == len(set(ids)), f"{CLAIMS}: claim ids must be unique"
    for r in rows:
        cid = r.get("id")
        assert isinstance(cid, str) and cid.strip(), "every claim needs a string id"
        assert isinstance(r.get("behaviour"), str) and r["behaviour"].strip(), f"{cid}: behaviour must be non-empty"
        assert isinstance(r.get("evidence"), list) and r["evidence"], f"{cid}: evidence must be a non-empty list"
        assert r.get("confidence") in CONFIDENCE, f"{cid}: confidence must be one of {sorted(CONFIDENCE)}"
        assert r.get("status", "active") in STATUS, f"{cid}: status must be one of {sorted(STATUS)}"


@stage(1)
@pytest.mark.parametrize("key", module_keys())
def test_module_has_an_active_claim(key):
    need_module(key)
    assert any(c.get("module") == key for c in active_claims()), f"no active claim describes module {key!r}"


@stage(1)
def test_claim_evidence_exists_in_the_jar():
    ref = need_reference()
    bad = sorted({f"{c.get('id')}: {e}" for c in active_claims() for e in (c.get("evidence") or [])
                  if not ref.resolve(e)})
    assert not bad, f"{len(bad)} cited classes or methods are not in the jar: {bad[:20]}"
