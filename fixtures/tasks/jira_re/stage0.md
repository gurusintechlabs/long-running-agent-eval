**Stage 0: onboarding, and a plan**

We are replacing a Jira Data Center plugin that we no longer have the source for. Our analyst has
studied it and written down what it does in `spec/`. Over the coming stages you will build a clean-room
replacement from that specification: a Jira plugin, built from this repository, that can be installed in
place of the original. This project is a pilot that covers part of that specification. Read `README.md`,
`CLAUDE.md` (project rules, binding), `ENVIRONMENT.md`, `spec/README.md` and `spec/PILOT.md` first, then the
claims and contract sections your scope needs. The whole of `spec/` is too large to read at once.

This stage is only about understanding the specification and planning. Do not start the rewrite yet.

Write `analysis/PLAN.md`:
- what the plugin is for, in your own words;
- the order in which you will build the modules in the pilot's scope, and why (what depends on what);
- which Jira APIs you expect to use, and whether `sh build.sh` already builds the empty skeleton;
- open questions about the spec (also in `analysis/QUESTIONS.md`, CLAUDE.md rule 3).

Commit it.
