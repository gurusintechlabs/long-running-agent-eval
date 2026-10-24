"""The single predicate for "does running or scoring this spec use the Claude subscription".

Audit of every path that starts the ``claude`` CLI (runner/ and scorer/):

* ``agent.runtime`` != scripted        runner/runtimes/claude_code.py, the agent itself
* ``scoring.judge_runtime`` != scripted  scorer/run_checkpoint.py X judge (every checkpoint); the
  behaviour judges (scorer/behavior/checkpoint.py behavior_judge_runner) follow the same field
* ``scoring.security.ai_review_runtime`` != scripted, when ``security.enabled`` and ``security.ai_review``
  (scorer/run_checkpoint.py ~410, scorer/security/checkpoint.py reviewer_for): the vulnerability review
* counterparts (ops, embed) and the exploit tests are local code, no CLI.

``CLASSIFIED_RUNTIME_FIELDS`` lists every runtime-typed field of the spec schema; a test fails when
spec/schema.py grows one that is not named here, so a new spending path cannot slip past the gate.
"""
from __future__ import annotations

CLASSIFIED_RUNTIME_FIELDS = (
    "agent.runtime",                       # spends: the agent
    "scoring.judge_runtime",               # spends: X judge + behaviour judges
    "scoring.security.ai_review_runtime",  # spends only if security.enabled and security.ai_review
)


def spend_reasons(spec) -> list[str]:
    s = spec
    out: list[str] = []
    if s.agent.runtime != "scripted":
        out.append(f"agent runtime {s.agent.runtime} uses the Claude subscription")
    if s.scoring.judge_runtime != "scripted":
        out.append(f"judge runtime {s.scoring.judge_runtime} uses the Claude subscription")
    sec = s.scoring.security
    if sec.enabled and sec.ai_review and sec.ai_review_runtime != "scripted":
        out.append(f"security AI review (runtime {sec.ai_review_runtime}) uses the Claude subscription")
    return out
