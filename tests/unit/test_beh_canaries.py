"""The behaviour canary scripts are generated (fixtures/scripted/build_beh_canaries.py) and up to date."""
import importlib.util

import yaml

from spec.loader import REPO_ROOT

SCRIPTED = REPO_ROOT / "fixtures" / "scripted"


def _builder():
    spec = importlib.util.spec_from_file_location("build_beh_canaries", SCRIPTED / "build_beh_canaries.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_scripts_are_up_to_date_and_cover_every_mode():
    b = _builder()
    built = b.canaries()
    assert set(built) == {"clean", "RH", "GM", "AF", "CE", "ED", "CP", "CF", "OK", "DC", "SE", "UA", "VI"}
    for name, stages in built.items():
        assert (SCRIPTED / f"beh_{name}.yaml").read_text() == b.render(stages), f"regenerate beh_{name}.yaml"


def test_each_canary_differs_from_the_clean_run_and_keeps_every_stage():
    b = _builder()
    built = b.canaries()
    clean = built["clean"]
    for name, stages in built.items():
        ends = sum(1 for st in stages for a in st if a == b.END)
        assert ends == len(clean) == 5, name                 # one finished turn per stage
        if name != "clean":
            assert stages != clean, name
        assert yaml.safe_load((SCRIPTED / f"beh_{name}.yaml").read_text())["actions"]
