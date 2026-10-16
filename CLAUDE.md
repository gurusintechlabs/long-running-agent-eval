# Long-Running Agent Evaluation Framework (LRAE)

Read these before any work: `docs/design.md` (source design, verbatim), `docs/spec.md` (implementable spec, decisions D-n), `docs/plan.md` (phase plan).

## Working rules (from design §4.1)
1. One phase per session. Read the docs first and restate the phase's exit check before coding.
2. Tests first, then code. A phase is done only when its exit check passes and `pytest` (plus `-m local`) is green.
3. Never place scorer code, hidden tests or scoring output inside the agent's work dir (`isolation.work_dir`, outside this repo).
4. Every run is reproducible from its spec file alone: pin model version, seed commit, CLI version and random seeds.
5. Log all events as append-only JSONL with timestamps. Derive every metric from the logs, never from agent self-reports.
6. Stop at the end of each phase and write `docs/phase-N-summary.md`: what was built, what was tested, what is unresolved.

## Guardrails for this repo
- Never run `api`-marked tests or real agent runs without explicit approval of the estimated spend.
- Do not change a spec decision (D-n) silently. Propose the change in the phase summary.
- Stack: Python 3.11, pytest, SQLite, JSONL, matplotlib, Jinja2 + headless Chrome, Node (pinned Claude Code CLI in `tools/`). Small Python libraries are OK. **Docker is optional** (Phase 7). Phases 1–6 run as local processes (D-14).
- Agent under test: the Claude Code CLI, headless, from `tools/claude-code/`, never the global `claude`. Model is set only in the experiment spec (`agent.model`, `scoring.judge_model`; default `claude-opus-5-5`).
- Agent subprocesses get a scrubbed env and an isolated `HOME`/`CLAUDE_CONFIG_DIR`. Never pass the host environment through.
- Checkpoint tags and all run artifacts stay on this machine (`runs/`, `tools/` gitignored). Never push them.
