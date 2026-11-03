**Stage 4: rewrite, part 3**

Implement every remaining module, to the same definition of `done` as in stage 2. At the end of this stage
every module of `spec/inventory.json` should be `done` in `analysis/rewrite_map.json`, and `sh build.sh`
should produce a plugin jar that could be installed in place of the original; if it could not, say why in
STATUS.

The public Java API must behave as the spec says: the tests in `spec/api-tests/`, copied into
`src/test/java/`, pass unchanged, and every API claim in `spec/claims.jsonl` is implemented and covered by a
JUnit test whose method name starts with the claim id, as for modules. Suspected bugs among the API claims are checked and listed in `analysis/SUSPECTED-BUGS.md`
as in stage 2.
