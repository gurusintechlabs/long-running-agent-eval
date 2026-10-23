"""t04 (stages 2-4): the replacement keeps the original's external contract in its plugin descriptor."""
import pytest

from _support import module_keys, need_module, original_plugin_key, rewrite_descriptor, stage


@stage(2)
def test_plugin_key_matches_the_original():
    want = original_plugin_key()
    if want is None:
        pytest.skip("the original jar has no atlassian-plugin.xml")
    got = rewrite_descriptor().plugin_key
    assert got == want, f"plugin key is {got!r} (after expanding pom properties); the original's is {want!r}"


@stage(2)
@pytest.mark.parametrize("key", module_keys())
def test_module_is_declared_with_its_original_key_and_type(key):
    m = need_module(key)
    got = rewrite_descriptor().modules.get(key)
    assert got is not None, f"module {key!r} is not declared in the replacement's atlassian-plugin.xml"
    assert got == m.element, f"module {key!r} is declared as <{got}>; the original's is <{m.element}>"
