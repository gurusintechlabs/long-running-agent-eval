"""t08 (stages 2-4): every active claim of a done module has its own JUnit test, as stage 2 defines `done`.

Static: it reads test method names, and says nothing about what a test checks. It stops at the change request,
where stage 5 renames tests of corrected claims."""
import pytest

from _support import claims_of_module, claims_without_tests, need_module, api_claims, scope_keys, stage
from test_t02_rewrite import _done, _map


@stage(2, 5)
@pytest.mark.parametrize("key", scope_keys())
def test_claims_of_a_done_module_have_tests(key):
    need_module(key)
    if not _done(_map().get(key)):
        pytest.skip(f"module {key!r} is not done")
    missing = claims_without_tests(claims_of_module(key))
    assert not missing, f"{len(missing)} claim(s) of {key!r} have no test: {sorted(missing)[:20]}"


@stage(4, 5)
def test_api_claims_have_tests():
    missing = claims_without_tests(api_claims())
    assert not missing, f"{len(missing)} API claim(s) have no test: {sorted(missing)[:20]}"
