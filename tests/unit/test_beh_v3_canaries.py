"""The minidb v3 behaviour canary scripts (fixtures/scripted/build_beh_v3_canaries.py): shape checks, no run."""
import importlib.util
import sys
from pathlib import Path

import yaml

from runner.runtimes.scripted_agent import load_script

REPO = Path(__file__).resolve().parents[2]
MODES = {"RH", "GM", "AF", "CE", "ED", "CP", "CF", "OK", "DC", "SE", "UA", "VI"}


def _builder():
    spec = importlib.util.spec_from_file_location("build_beh_v3", REPO / "fixtures/scripted/build_beh_v3_canaries.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_beh_v3"] = mod
    spec.loader.exec_module(mod)
    return mod


B = _builder()


def turns(script):
    out, cur = [], []
    for a in script["actions"]:
        cur.append(a)
        if a["do"] == "end_turn":
            out.append(cur)
            cur = []
    assert not cur, "every turn ends"
    return out


def test_every_script_is_valid_and_has_one_turn_per_stage(tmp_path):
    scripts = B.scripts()
    assert set(scripts) == MODES | {"clean"}
    for name, s in scripts.items():
        p = tmp_path / f"{name}.yaml"
        p.write_text(yaml.safe_dump(s))
        load_script(p)
        assert len(turns(s)) == B.STAGES, name


def test_the_clean_replay_reads_the_inbox_first_and_writes_each_reference_overlay():
    ts = turns(B.scripts()["clean"])
    for k, t in enumerate(ts):
        assert t[0] == B.INBOX, k                                    # CLAUDE.md rule 8, before any change
        assert "```status" in t[-2]["event"]["message"]["content"][0]["text"], k
        written = {a["path"]: a["content"] for a in t if a["do"] == "write_file"}
        overlay = REPO / "fixtures/snapshots" / f"minidb_v3_s{k}" / "overlay"
        want = {p.relative_to(overlay).as_posix(): p.read_text() for p in overlay.rglob("*") if p.is_file()} \
            if overlay.is_dir() else {}
        assert written == want, k
    assert not [a for a in ts[10] if a["do"] in ("write_file", "git_commit", "bash")]   # Dana: nothing changes


def test_a_canary_is_the_clean_replay_with_its_trap_stage_changed():
    scripts, ref = B.scripts(), turns(B.scripts()["clean"])
    for mode, changed in B.canaries().items():
        ts, last = turns(scripts[mode]), max(changed)
        for k in range(B.STAGES):
            if k in changed:
                assert ts[k] == changed[k] and ts[k] != ref[k], (mode, k)
            elif k < last:
                assert ts[k] == ref[k], (mode, k)
            else:
                assert ts[k] == [B.END], (mode, k)
        assert ts[last][0] == B.INBOX or mode == "CP", mode           # CP keeps the reference's own first action


def test_the_clean_replay_never_names_a_marker_of_the_recorded_judges():
    rules = yaml.safe_load((REPO / "fixtures/behavior_v3/judges.yaml").read_text())
    text = yaml.safe_dump(B.scripts()["clean"])
    assert not [r["when_contains"] for r in rules if r["when_contains"] in text]
