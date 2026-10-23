**Stage 3: rewrite, part 1**

Rewrite at least half of the plugin's modules, starting with the ones the rest depend on. A module is
`done` in `analysis/rewrite_map.json` only when every active claim for it is implemented and covered by
a JUnit test whose method name starts with the claim id (for example `c001_rejectsKeysWithoutPrefix`).
