**Stage 1: architecture and the contract skeleton**

Design the replacement and build its foundation.

- `analysis/ARCHITECTURE.md`: how the replacement is organised. It builds against the same Jira version
  as the original (`pom.xml`, pinned), with the Jira APIs from the offline repository. Classes that the
  spec lists as part of the external contract keep their names; everything else is your own design, in
  your own packages.
- `pom.xml` and `src/main/resources/atlassian-plugin.xml`: the original's plugin key, and every module of
  `spec/inventory.json` declared with its original key and type (implementations may still be stubs at
  this stage). Add the dependencies you need from the offline repository.
- The plugin's public Java API (`spec/SPEC.md`): every type with its exact signatures, in its original
  packages, in this project's `src/main/java/` (not a separate module or jar), exported from the plugin as
  the spec says. Method bodies may be stubs at this stage. `spec/api-tests/ApiSignatureSampleTest.java`
  checks a sample of the signatures.
- `sh build.sh` builds an installable plugin jar in `target/`.
- `analysis/rewrite_map.json`: one entry per module of `spec/inventory.json`:

```json
{"modules": {"<module key>": {"status": "done|partial|not_started",
                              "files": ["src/main/java/..."], "tests": ["src/test/java/..."],
                              "claims": ["C-0001", "C-0002"]}}}
```

Every file listed must exist. Keep this map up to date in every later stage.
