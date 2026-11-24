"""t06 (from stage 4): the analyst's hidden Java tests of the public API pass on the rewrite.

Written from the spec against the API (``api/hidden/``), and checked to pass against the real library
(``analyst/selfcheck_api.py``). One test per Java test method."""
import pytest

import _api
from _support import stage

TESTS = {t.id: t for t in _api.java_tests(_api.HIDDEN_TESTS)}


@stage(_api.BEHAVIOUR_STAGE)
@pytest.mark.parametrize("test_id", _api.test_ids(_api.HIDDEN_TESTS))
def test_api_behaviour(test_id):
    if not _api.api_jars():
        pytest.skip("the plugin bundles no public API (target.yaml public_api)")
    if test_id == _api.NO_TESTS:
        pytest.skip("no hidden API behaviour tests yet")
    why = _api.outcome_message(_api.session_build(True), TESTS[test_id])
    assert why is None, why
