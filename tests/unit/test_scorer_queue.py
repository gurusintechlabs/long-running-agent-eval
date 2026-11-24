"""The checkpoint scorer queue (runner/scoring.py): one job at a time, timed-out jobs retried after the run."""
import json
import stat
import sys

from runner.scoring import ScorerQueue
from telemetry.events import EventWriter

# Stands in for ``python -m scorer.run_checkpoint``: slow the first time it scores a checkpoint listed in
# SLOW, fast after that (the agent is gone and the machine is free).
FAKE = """#!{python}
import pathlib, sys, time
k = sys.argv[sys.argv.index("--k") + 1]
seen = pathlib.Path({seen!r}) / k
first = not seen.exists()
seen.write_text("x")
time.sleep(4.0 if first and k in {slow!r} else 0.0)
"""


def queue(tmp_path, slow):
    seen = tmp_path / "seen"
    seen.mkdir()
    fake = tmp_path / "fake-python"
    fake.write_text(FAKE.format(python=sys.executable, seen=str(seen), slow=list(slow)))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    events = EventWriter(tmp_path / "orchestrator.jsonl", "run", "orchestrator")
    q = ScorerQueue(tmp_path / "art", tmp_path / "spec.yaml", events, repo_root=tmp_path, python=str(fake),
                    timeout_s=2.0, retry_timeout_s=10.0)
    return q, events


def finished(tmp_path):
    rows = [json.loads(x) for x in (tmp_path / "orchestrator.jsonl").read_text().splitlines()]
    return [(e["type"], e["payload"]["k"], e["payload"].get("returncode")) for e in rows
            if e["type"] in ("scorer.finished", "scorer.retry")]


def test_a_checkpoint_that_timed_out_during_the_run_is_scored_again_at_the_end(tmp_path):
    """jira-re full run: checkpoints 9, 12, 13 and 14 hit the 30-minute limit while the agent's subagents
    were building in parallel; each scored in about 15 minutes once the run was over."""
    q, events = queue(tmp_path, slow={"2"})
    for k in (1, 2, 3):
        q.submit(k)
    assert q.drain(timeout_s=30)
    events.close()
    assert finished(tmp_path) == [("scorer.finished", 1, 0), ("scorer.finished", 2, None),
                                  ("scorer.finished", 3, 0), ("scorer.retry", 2, None),
                                  ("scorer.finished", 2, 0)]
    assert q.results == {1: 0, 2: 0, 3: 0}


def test_nothing_is_retried_when_every_checkpoint_scored(tmp_path):
    q, events = queue(tmp_path, slow=set())
    q.submit(1)
    assert q.drain(timeout_s=30)
    events.close()
    assert finished(tmp_path) == [("scorer.finished", 1, 0)]
