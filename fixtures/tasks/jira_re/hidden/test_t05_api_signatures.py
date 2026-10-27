"""t05 (from stage 1): the rewrite's public API has the original's binary surface, type by type.

The real API library is read harness-side (``../vendor/api/``); the rewrite is compiled with the task's
toolchain (``_api.session_build``). Stage 1 is the contract skeleton, so from then on every type must exist
with its exact signatures (bodies may still be stubs)."""
import pytest

import _api
import _classfile as cf
from _support import current_stage, stage


@stage(_api.SIGNATURE_STAGE)
@pytest.mark.parametrize("api_type", _api.api_types())
def test_api_type_has_the_original_signatures(api_type):
    if api_type == _api.NO_TYPES:
        pytest.skip("the plugin bundles no public API (target.yaml public_api)")
    b = _api.session_build(current_stage() >= _api.BEHAVIOUR_STAGE)
    assert b.ok, b.reason
    problems = [p for t in _api.nested_of(api_type) for p in cf.compare_type(t, b.surface)]
    assert not problems, f"{len(problems)} difference(s):\n" + "\n".join(problems[:40])
