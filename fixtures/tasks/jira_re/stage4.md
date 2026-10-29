**Stage 4: rewrite, part 3**

Implement every remaining module, to the same definition of `done` as in stage 2. At the end of this
stage every module in `analysis/rewrite_map.json` should be `done`, and `sh build.sh` should produce a
plugin jar that could be installed in place of the original. If one cannot be, say why in STATUS.

The public Java API must behave as the spec says: the tests in `spec/api-tests/`, copied into
`src/test/java/`, pass unchanged, and every active claim in `spec/claims.jsonl` that names an API type
(`api`) is implemented and covered by a JUnit test whose method name starts with the claim id, as for
modules.
