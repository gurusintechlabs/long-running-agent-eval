# Long-Running Agent Evaluation Framework (LRAE)

Read these before any work: `docs/design.md` (source design, verbatim), `docs/spec.md` (implementable spec, decisions D-n), `docs/plan.md` (phase plan).

## Working rules (from design §4.1)
1. One phase per session. Read the docs first and restate the phase's exit check before coding.
2. Tests first, then code. A phase is done only when its exit check passes and `pytest` (plus `-m docker`) is green.
3. Never place scorer code, hidden tests or scoring output inside the agent's sandbox, image or mounted volumes.
4. Every run is reproducible from its spec file alone: pin model version, seed commit, image digest and random seeds.
5. Log all events as append-only JSONL with timestamps. Derive every metric from the logs, never from agent self-reports.
6. Stop at the end of each phase and write `docs/phase-N-summary.md`: what was built, what was tested, what is unresolved.

## Guardrails for this repo
- Never run `api`-marked tests or real agent runs without explicit approval of the estimated spend.
- Do not change a spec decision (D-n) silently. Propose the change in the phase summary.
- Stack: Python 3.11, Docker, pytest, SQLite, JSONL, matplotlib, Jinja2 + headless Chrome. No extra services.
