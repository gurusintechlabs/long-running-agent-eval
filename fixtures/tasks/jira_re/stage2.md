**Stage 2: rewrite architecture**

Design the rewrite and build its foundation. From this stage on, the rewrite under `src/` is written from
`analysis/SPEC.md` and `analysis/claims.jsonl`, not from the decompiled code (CLAUDE.md rule 5). If
the spec is missing something you need, go back to the decompiled code, update the spec and the claims
first, then write the code.

- `analysis/ARCHITECTURE.md`: how the rewrite is organised (Java 21, JDK and JUnit only), and how it
  stands in for the Jira APIs the plugin uses. The Jira API jars are not available here, so define
  small interfaces of your own for issues, users, projects, workflows and whatever else the plugin
  touches, plus in-memory implementations for tests. Choose your own package names; do not copy the
  original's.
- `src/main/java/`: that Jira abstraction layer, with tests in `src/test/java/`.
- `analysis/rewrite_map.json`: one entry per module of the plugin:

```json
{"modules": {"<module key>": {"status": "done|partial|not_started",
                              "files": ["src/main/java/..."], "tests": ["src/test/java/..."],
                              "claims": ["C-001", "C-002"]}}}
```

Every file listed must exist. Keep this map up to date in every later stage.
