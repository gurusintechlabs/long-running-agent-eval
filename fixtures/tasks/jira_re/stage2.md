**Stage 2: rewrite architecture**

Design the rewrite and build its foundation. From this stage on, the rewrite under `src/` is written from
`analysis/SPEC.md` and `analysis/claims.jsonl`, not from the decompiled code (CLAUDE.md rule 5). If
the spec is missing something you need, go back to the decompiled code, update the spec and the claims
first, then write the code.

- `analysis/ARCHITECTURE.md`: how the replacement is organised. It builds against the same Jira
  version as the original (`pom.xml`, pinned), with the Jira APIs from the offline repository. Classes
  that are part of the external contract keep their names; everything else is your own design, in your
  own packages.
- `pom.xml` and `src/main/resources/atlassian-plugin.xml`: the original's plugin key, and every module
  declared with its original key and type (implementations may still be stubs at this stage). Add the
  dependencies you need from the offline repository.
- `sh build.sh` builds an installable plugin jar in `target/`.
- `analysis/rewrite_map.json`: one entry per module of the plugin:

```json
{"modules": {"<module key>": {"status": "done|partial|not_started",
                              "files": ["src/main/java/..."], "tests": ["src/test/java/..."],
                              "claims": ["C-001", "C-002"]}}}
```

Every file listed must exist. Keep this map up to date in every later stage.
