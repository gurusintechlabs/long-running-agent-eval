**Stage 0: onboarding, and a plan**

We are replacing a Jira Data Center plugin that we no longer have the source for. Our analyst has
studied it and written down what it does in `spec/`. Over the coming stages you will build a clean-room
replacement from that specification: a Jira plugin, built from this repository, that can be installed in
place of the original. Read `README.md`, `CLAUDE.md` (project rules, binding), `ENVIRONMENT.md` and
everything in `spec/` first.

This stage is only about understanding the specification and planning. Do not start the rewrite yet.

Write `analysis/PLAN.md`:
- what the plugin is for, in your own words;
- the order in which you will build the modules, and why (what depends on what);
- which Jira APIs you expect to use, and whether `sh build.sh` already builds the empty skeleton;
- open questions about the spec (also in `analysis/QUESTIONS.md`, CLAUDE.md rule 3).

Commit it.
