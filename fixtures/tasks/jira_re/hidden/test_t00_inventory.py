"""t00 (stage 0): the inventory names every module of the plugin, with evidence that exists in the jar."""
import pytest

from _support import load_json, module_keys, need_module, need_reference, stage

INVENTORY = "analysis/inventory.json"


def _inventory() -> dict:
    inv = load_json(INVENTORY)
    assert isinstance(inv, dict), f"{INVENTORY} must be an object"
    assert isinstance(inv.get("modules"), list), f"{INVENTORY}: 'modules' must be a list"
    assert isinstance(inv.get("classes"), list), f"{INVENTORY}: 'classes' must be a list"
    return inv


@stage(0)
def test_inventory_has_the_required_shape():
    inv = _inventory()
    for i, m in enumerate(inv["modules"]):
        assert isinstance(m, dict), f"modules[{i}] must be an object"
        for k in ("key", "type", "purpose"):
            assert isinstance(m.get(k), str) and m[k].strip(), f"modules[{i}].{k} must be a non-empty string"
        assert isinstance(m.get("evidence"), list) and m["evidence"], f"modules[{i}].evidence must be a non-empty list"
    for i, c in enumerate(inv["classes"]):
        assert isinstance(c, dict) and isinstance(c.get("name"), str), f"classes[{i}].name must be a string"


@stage(0)
@pytest.mark.parametrize("key", module_keys())
def test_module_is_inventoried(key):
    need_module(key)
    keys = {m.get("key") for m in _inventory()["modules"] if isinstance(m, dict)}
    assert key in keys, f"module {key!r} of atlassian-plugin.xml is not in {INVENTORY}"


@stage(0)
def test_inventory_evidence_exists_in_the_jar():
    ref = need_reference()
    inv = _inventory()
    refs = [e for m in inv["modules"] if isinstance(m, dict) for e in (m.get("evidence") or [])]
    refs += [c.get("name") for c in inv["classes"] if isinstance(c, dict)]
    bad = sorted({str(r) for r in refs if not ref.resolve(r)})
    assert not bad, f"{len(bad)} evidence references are not in the jar: {bad[:20]}"
