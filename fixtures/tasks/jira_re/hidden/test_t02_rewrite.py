"""t02 (stages 1-4): the clean-room rewrite (Java) maps every module to code and tests that exist.

Stage 1 lays the skeleton; stages 2, 3 and 4 bring a third, two thirds and all of the pilot's modules to done
(spec/PILOT.md)."""
import pytest

from _support import WS, load_json, need_module, need_reference, scope_keys, stage

MAP = "analysis/rewrite_map.json"
STATUSES = {"done", "partial", "not_started"}


def _map() -> dict:
    m = load_json(MAP)
    assert isinstance(m, dict) and isinstance(m.get("modules"), dict), f"{MAP}: 'modules' must be an object"
    return m["modules"]


def _done(entry) -> bool:
    if not isinstance(entry, dict) or entry.get("status") != "done":
        return False
    files = [f for f in entry.get("files") or [] if isinstance(f, str) and f.startswith("src/main/java/")
             and f.endswith(".java")]
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
    done = sum(_done(entries.get(k)) for k in keys)
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
    need_module(key)
    assert _done(_map().get(key)), f"module {key!r} is not done (status, src/main/java and src/test/java files)"
