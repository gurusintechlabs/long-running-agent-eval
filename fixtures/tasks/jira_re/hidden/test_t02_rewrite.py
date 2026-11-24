"""t02 (stages 1-4): the clean-room rewrite (Java) maps every module to code and tests that exist.

Stage 1 lays the skeleton; stages 2, 3 and 4 bring a third, two thirds and all of the modules to done
(spec/inventory.json)."""
import pytest

from _support import WS, Module, load_json, need_module, need_reference, scope_keys, stage

MAP = "analysis/rewrite_map.json"
STATUSES = {"done", "partial", "not_started"}


def _map() -> dict:
    m = load_json(MAP)
    assert isinstance(m, dict) and isinstance(m.get("modules"), dict), f"{MAP}: 'modules' must be an object"
    return m["modules"]


# Modules the original declares without a class that are still Java: REST resources and AO entities
JAVA_WITHOUT_CLASS = {"rest", "ao"}


def _needs_java(module: Module | None) -> bool:
    """A module the original declares without a class (web resources, items, sections, ...) is implemented
    in the descriptor and front-end files, so its code need not be under src/main/java."""
    return module is None or module.cls is not None or module.element in JAVA_WITHOUT_CLASS


def _done(entry, module: Module | None = None) -> bool:
    if not isinstance(entry, dict) or entry.get("status") != "done":
        return False
    prefix = ("src/main/java/", ".java") if _needs_java(module) else ("src/main/", "")
    files = [f for f in entry.get("files") or [] if isinstance(f, str) and f.startswith(prefix[0])
             and f.endswith(prefix[1])]
    tests = [f for f in entry.get("tests") or [] if isinstance(f, str) and f.startswith("src/test/java/")
             and f.endswith(".java")]
    return bool(files and tests) and all((WS / f).is_file() for f in files + tests)


@stage(1)
def test_rewrite_map_has_the_required_shape():
    for key, e in _map().items():
        assert isinstance(e, dict), f"{key}: entry must be an object"
        assert e.get("status") in STATUSES, f"{key}: status must be one of {sorted(STATUSES)}"
        for f in (e.get("files") or []) + (e.get("tests") or []):
            assert (WS / f).is_file(), f"{key}: listed file {f} does not exist"


def _share_done(thirds: int) -> None:
    ref = need_reference()
    if not ref.modules:
        pytest.skip("the jar has no atlassian-plugin.xml modules")
    entries = _map()
    keys = scope_keys()
    modules = {m.key: m for m in ref.modules}
    done = sum(_done(entries.get(k), modules.get(k)) for k in keys)
    assert 3 * done >= thirds * len(keys), f"{done} of {len(keys)} modules in scope are done"


@stage(2)
def test_at_least_a_third_of_the_modules_are_rewritten():
    _share_done(1)


@stage(3)
def test_at_least_two_thirds_of_the_modules_are_rewritten():
    _share_done(2)


@stage(4)
@pytest.mark.parametrize("key", scope_keys())
def test_module_is_rewritten(key):
    module = need_module(key)
    where = "src/main/java" if _needs_java(module) else "src/main"
    assert _done(_map().get(key), module), f"module {key!r} is not done (status, {where} and src/test/java files)"
