# Phase B4 Summary: security scoring (SAST, exploit suite, AI review)

**Branch:** `behavior-improvements` · **Design:** `docs/behavior-design.md` §7 (D-23) · **Contract:** `docs/interfaces.md` §4 ·
**Date:** 2026-10-20

## Exit check status

> The planted-vulnerability snapshot is flagged by the exploit suite (every planted exploitable
> weakness) and by CE SAST (the SAST-detectable ones); the reference snapshot has zero exploit
> failures and zero new High SAST findings after suppressions. Verification: one real AI review and
> one semgrep Pro scan.

**Met**, on a purpose-built fixture, because minidb v3 does not exist yet (B6). The fixture is
`fixtures/security/vulnapp`: a stdlib HTTP file service in a clean and a vulnerable variant (path
traversal, shell injection, pickle of request bodies, a hard-coded password), plus four black-box
exploit tests. `known_vuln` for v3 is built in B6 against the same machinery.

`tests/integration/test_scorer_security.py` runs two scored scripted runs, each with two stages:

| | vulnerable (the agent swaps in the bad variant) | clean |
|---|---|---|
| `SEC_exploits` | **3** (traversal, shell, pickle); `security` hazard `exploit_succeeded` | 0, no hazard |
| `SEC_new` | ≥ 2: bandit B602 (high), B301 (medium), semgrep CE `subprocess-shell-true` | 0 |
| `SEC_ai` (FakeReviewer, one review per completed stage: stage 0 at stage 1's delivery, stage 1 at `run.done`) | ≥ 2 | 0, all reviews `sound` |

**Verification** (approved; Haiku as the reviewer for now, as the owner suggested):
- **AI review of the minidb v2 final reference:** ok on the first attempt, **$0.21, about 9 minutes**,
  36 KB report. 12 findings, all Medium or Low (none counted), and 3 chains. They are plausible for a
  SQL engine: LIKE compiled to a backtracking regex (ReDoS), unbounded resource use, no fsync on the
  WAL, symlink-following temp files, and a loader that trusts the DB file contents.
- **semgrep Pro (local, logged in):** the first run failed ("Inter-file analysis can only take a
  single target"), so Pro now scans the tree directory with excludes. Then:
  - minidb v2: 0 findings, 19 s;
  - vulnerable fixture: Pro's taint analysis also finds the **path traversal**, which bandit and CE
    miss;
  - clean fixture: one **false positive** (it does not recognise the resolve-and-check sanitiser).

  So Pro stays supplementary: recorded, not counted.
- bandit and semgrep CE on minidb v2: 0 security findings. The 17 bandit B608 hits of the first real
  run came from the agent's benchmark script, not the engine, and are low-signal noise either way.

## What was built

| Area | Files |
|---|---|
| SAST: bandit + semgrep CE (pinned `semgrep-rules@311ca4e9…`, `category: security` only) + semgrep Pro (`scan --pro`, directory target with excludes, `reproducible: false`); fingerprints; new/fixed; scorer-owned suppressions; never `semgrep ci` | `scorer/security/sast.py`, `scorer/security/rules.py` |
| Exploit suite: `task.exploit_tests`, run like the hidden suite (own `scorer.yaml`, stage window), kept apart from P(t) | `scorer/security/checkpoint.py`, `spec/schema.py` |
| AI review: the owner's prompt plus the harness wrapper; a separate `claude -p` with Read/Grep/Glob on a code copy (no tests, `.git` or harness files); `lrae-findings` JSON, one retry, null on failure, cache by code+prompt+model; spend gate; 45 min timeout; FakeReviewer | `scorer/security/ai_review.py`, `scorer/vuln_review_prompt.md` |
| One review per completed stage: the orchestrator records `head_sha`/`dirty` on `stage.delivered` and `run.done` | `runner/orchestrator.py`, `scorer/security/checkpoint.py` |
| Metrics `SEC_new`, `SEC_open`, `SEC_exploits`, `SEC_ai`; hazard dimension `security` (D-22) | `scorer/run_checkpoint.py`, `scorer/hazards.py` |
| Spec: `scoring.security {enabled, semgrep_version, semgrep_rules_commit, semgrep_rulesets, semgrep_pro_configs, ignore, ai_review, ai_review_model, ai_review_runtime, context_file}`, `task.exploit_tests` (hashed only when used; example hashes unchanged) | `spec/schema.py`, `spec/loader.py` |
| Fixture app, exploit tests, minidb v2 security context | `fixtures/security/vulnapp/`, `fixtures/tasks/minidb_v2/security_context.yaml` |

## What was tested

- `tests/unit/scorer/test_sec_sast.py` (6): fingerprint stability, parsers and severity, the semgrep
  category filter, compare/ignore, command flags (no upload; Pro uses a directory), Pro unavailable →
  skipped with a reason, real clean vs vulnerable scans.
- `tests/unit/scorer/test_sec_ai_review.py` (7): prompt filling, the `lrae-findings` schema, code-copy
  exclusions, retry then cache, failure → null and not cached, FakeReviewer, the read-only CLI
  command and the spend gate.
- `tests/unit/scorer/test_hazards.py` (security dimension), `tests/unit/test_spec_schema.py` (security
  fields).
- Integration: `tests/integration/test_scorer_security.py` (2).
- Suites:
  - default `pytest`: 706 passed, 1 skipped;
  - `pytest -m local`: 121, all green (about 17 min);
  - `ruff check .`: clean.

  The first default run caught a race in the B3 mock embedding API: it logged each request after
  replying, so a fast reader could miss the entry. It now logs before replying (fixed here).

## Unresolved / needs the owner

1. ~~Review model~~: **Opus stays the reviewer** (owner, 2026-10-20). Haiku was only used for the
   verification. `ai_review_model` defaults to `scoring.judge_model` (Opus). At v3 scale a review will
   take longer than Haiku's 9 minutes; reviews run in the scorer queue and do not block the agent.
2. ~~Reconstructed prompt fields~~: **kept as reconstructed** (owner delegated the decision). The
   prompt is now v1 and hashed into `spec_hash` when the AI review is enabled.
3. **No per-commit attribution for security** (SAST or exploits): a hazard is attributed to t_k.
   Attribution would mean re-running the exploit suite per commit; worth it only if t_k proves too
   coarse.
4. **Uncommitted work at a stage end is not reviewed:** the review reads the stage's `head_sha`.
   `dirty: true` is recorded so the analysis can flag it.
5. **semgrep comes from Homebrew**, not the scorer venv. `scoring.security.semgrep_version` pins it,
   and a mismatch marks CE results `reproducible: false` with a warning.
