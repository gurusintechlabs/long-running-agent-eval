**Stage 2: rewrite, part 1**

Implement at least a third of the modules of `spec/inventory.json`, starting with the ones the rest depend on. A module
is `done` in `analysis/rewrite_map.json` only when every active claim for it in `spec/claims.jsonl` is
implemented and covered by a JUnit test whose method name starts with the claim id (for example
`c0001_rejectsKeysWithoutPrefix`).

Claims about the browser are no exception: test them with Playwright and jsoup, as `ENVIRONMENT.md` explains. If
a claim needs a real Jira page and cannot be checked that way, test what you can and list the claim in
`analysis/UNTESTED-CLAIMS.md` with the reason; such a claim counts as covered only with that entry.

Some claims carry `"suspected_bug": true`: the analyst believes the original behaves that way by mistake.
Implement them exactly as stated, like any other claim, and check each one while you implement it: list it
in `analysis/SUSPECTED-BUGS.md`, one entry per claim id, saying whether you agree that it is a bug, what the
behaviour would be if it were fixed, and what a fix would affect (callers, stored data, other claims). Do not
fix them on your own: a product owner decision would come as a change request.
