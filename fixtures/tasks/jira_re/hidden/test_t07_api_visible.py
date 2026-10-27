"""t07 (from stage 4): the pristine copy of the visible API tests (the seed's ``spec/api-tests/``) passes on
the rewrite. The agent's own copy may have been edited; this one cannot have been. One test per Java test
method."""
import pytest

import _api
from _support import stage

TESTS = {t.id: t for t in _api.java_tests(_api.VISIBLE_TESTS)}


@stage(_api.BEHAVIOUR_STAGE)
@pytest.mark.parametrize("test_id", _api.test_ids(_api.VISIBLE_TESTS))
def test_api_visible(test_id):
    if not _api.api_jars():
        pytest.skip("the plugin bundles no public API (target.yaml public_api)")
    if test_id == _api.NO_TESTS:
        pytest.skip("no visible API tests yet")
    why = _api.outcome_message(_api.session_build(True), TESTS[test_id])
    assert why is None, why
