"""t09 (stages 5+): each claim the change request replaced is replaced in the tests, the map and the report.

Static, like t08: it reads names, and says nothing about what a test checks."""
import pytest

from _support import change_problems, changes, scope_keys, stage


@stage(5)
@pytest.mark.parametrize("change", changes(), ids=lambda c: c.new)
def test_change_is_applied(change):
    if change.module not in scope_keys():
        pytest.skip(f"this jar has no module {change.module!r}")   # a synthetic plugin
    assert not change_problems(change), f"{change.old} -> {change.new}: {sorted(change_problems(change))}"
