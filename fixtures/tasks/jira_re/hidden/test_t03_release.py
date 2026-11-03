"""t03 (stage 6): RELEASE.md accounts for every module."""
import pytest

from _support import WS, need_module, scope_keys, stage


@stage(6)
@pytest.mark.parametrize("key", scope_keys())
def test_release_names_the_module(key):
    need_module(key)
    rel = WS / "RELEASE.md"
    assert rel.is_file(), "RELEASE.md is missing"
    assert key in rel.read_text(), f"RELEASE.md does not mention module {key!r}"
