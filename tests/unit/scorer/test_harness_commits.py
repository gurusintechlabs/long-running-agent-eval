"""Commits the harness makes in the agent's repo (environment stages, D-18a) are never agent work:
not accepted commits (S), not per-commit scoring points, not "own" lines for W, not judge input."""
import os
import subprocess

import pytest

from scorer.metrics import r_regression
from scorer.metrics.w_repeat import repeat_work


def git(repo, *args, author=("agent", "agent@lrae.local")):
    env = {**os.environ, "GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1],
           "GIT_COMMITTER_NAME": author[0], "GIT_COMMITTER_EMAIL": author[1]}
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


BOT = ("platform-bot", "platform-bot@harness.lrae.local")


def commit(repo, files, msg, author=("agent", "agent@lrae.local")):
    for rel, text in files.items():
        (repo / rel).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, author=author)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    seed = commit(r, {"a.py": "seed\n"}, "seed")
    c1 = commit(r, {"b.py": "own1\nown2\n"}, "agent work 1")
    bot = commit(r, {"ENV.md": "env1\nenv2\nenv3\n"}, "Update environment", author=BOT)
    c2 = commit(r, {"c.py": "own3\n"}, "agent work 2")
    bare = tmp_path / "mirror.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(r), str(bare)], check=True)
    return dict(repo=r, mirror=bare, seed=seed, c1=c1, bot=bot, c2=c2)


def test_commits_between_skips_harness_commits(history):
    h = history
    assert r_regression.commits_between(h["mirror"], h["seed"], h["c2"]) == [h["c1"], h["c2"]]


def test_agent_commit_messages_skip_harness_commits(history):
    h = history
    assert r_regression.agent_commit_messages(h["mirror"], h["seed"], h["c2"]) == ["agent work 1", "agent work 2"]


def test_lines_a_harness_commit_added_are_not_own_work(history):
    h = history
    # interval (c2, c3]: the agent deletes the bot's ENV.md lines and one of its own lines
    c3 = commit(h["repo"], {"ENV.md": "env1\n", "b.py": "own1\n", "d.py": "new\n"}, "agent work 3")
    w = repeat_work(h["repo"], h["seed"], h["c2"], c3)
    assert w["lines_deleted_own"] == 1           # own2 only; env2/env3 belong to the harness
    assert w["detail"]["own_commits"] == 2
