"""Replay every tool call of the first real minidb v2 run (anonymised: fixtures/guardrails/) through
the policy with the monitor's cwd model. That run raised 39 `other-outside` warnings, nearly all
false positives (heredoc text read as shell, `cd -` read as `cd ~`). The only genuine outside
accesses were to /tmp (allowed scratch space), so at most 2 warnings may remain (plan B2)."""
import gzip
import json
from pathlib import Path

from guardrails.monitor import CwdModel
from guardrails.policy import load_policy

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "guardrails" / "v2_tool_calls.jsonl.gz"


def test_v2_replay_other_outside_false_positives_gone(tmp_path):
    home = tmp_path.resolve() / "home"
    work = home / "lrae-work" / "run"
    ws = work / "workspace"
    for d in (ws / "minidb", ws / "tests", ws / "benchmarks", home / ".claude" / "projects"):
        d.mkdir(parents=True, exist_ok=True)
    repo = tmp_path.resolve() / "repo"
    repo.mkdir()
    pol = load_policy(ROOT / "guardrails" / "rules" / "default.yaml").bind(work, repo, home / ".claude" / "x", home)
    text = gzip.open(FIXTURE, "rt").read()
    text = text.replace("@@WS@@", str(ws)).replace("@@WORK@@", str(work)).replace("@@HOME@@", str(home))
    model = CwdModel(pol, ws)
    found = []
    for line in text.splitlines():
        row = json.loads(line)
        if row.get("session"):
            model.reset()
            continue
        found += model.check(row["tool"], row["input"])
    # nothing in that run was out of bounds: at most 2 findings of any rule (B2 adds log-only rules
    # for destructive git, kills, sudo, network code; heredoc text must not trigger them)
    assert len(found) <= 2, [(v.rule_id, v.evidence[:200]) for v in found]
    assert not [v for v in found if v.severity == "violation"], [v.evidence[:200] for v in found]
