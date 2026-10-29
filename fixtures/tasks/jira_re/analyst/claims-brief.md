# JC2 helper brief: behavioural claims for the plugin's public service components

Repo: /Users/tonylee/Documents/coding/longhorizon_testing (branch jira-re). You are an analyst helper in a
clean-room reverse-engineering project. Another engineer (an AI agent) will re-implement this Jira plugin
**from our spec alone** and never sees the original code. You write **claims**: one testable behaviour per
claim, in your own words. Hidden tests check the re-implementation against them.

This session covers the plugin's **public components**: the 45 Spring components the plugin exports to other
plugins, each implementing one or more interfaces of the public Java API. Many API interfaces are pure (no code
of their own); their behaviour is claimed **here, through the module that implements them**.

## Your inputs
- Your modules: `modules.txt` in your own scratch folder (path in your prompt): module key, the original's
  implementing class (internal, never name it in a claim), the exported API interfaces, purpose, SPEC.md lines.
- Decompiled source (Vineflower): the plugin in `analyst-work/vf/`, its internal libraries in
  `analyst-work/libvf/<lib>/` (much real logic lives in structure-commons), the public API in
  `analyst-work/apivf/`. Class files: `analyst-work/jar/` (plugin), `analyst-work/apijar/` (API), the libraries
  as jars in `analyst-work/jar/META-INF/lib/`. Tools: `~/lrae-tools/re/bin/javap` (`javap -c -p -cp DIR CLASS`).
- **The decompiler drops some `throw`s.** `fixtures/tasks/jira_re/analyst/dropped-throws.txt` lists every class
  where the bytecode throws more than the source shows. For those classes, and wherever an error path matters
  and looks odd, read the method with `javap -c -p`.
- The spec already written, which your claims must agree with:
  - `fixtures/seed_jira_re/spec/API.md`: every API type and member, with a one-line meaning. Search
    `### \`<fq type>\``. Your module's interfaces are there.
  - `fixtures/seed_jira_re/spec/SPEC.md` Part 1: module table (§1.2), REST (§1.3), Active Objects tables and
    columns (§1.5), persisted names such as property keys (§1.6), and §1.8 (out of scope: contacting the
    vendor; the replacement never phones home, and no Marketplace licensing: every licence check behaves as
    licensed and valid).
  - `fixtures/seed_jira_re/spec/claims.jsonl`: existing claims (API types). Do not repeat them; build on them.
  - If API.md or SPEC.md is wrong, say so in your report; do not edit them.
- **Never read `analyst-work/central-src/`, and keep it out of every search** (search `vf/`, `libvf/`, `apivf/`
  by name, or use `grep -r --exclude-dir=central-src`). It is the vendor's source with javadoc. Copying from
  it is the one thing that breaks the clean room.

## Your output: exactly one file
`fixtures/tasks/jira_re/analyst/claim-notes/<group>.json`, the only file you write in the repo. Scratch
scripts or notes go in your own scratch folder only.

```json
{"claims": [
  {"key": "<group>/<module-key>/<short-slug>",
   "module": "<module key from modules.txt>",
   "api": null,
   "behaviour": "One behaviour, testable from outside, in plain English.",
   "confidence": "high|medium|low",
   "evidence": ["fq.Class#method", "fq.Class$Inner#method"]}
 ]}
```
- `module` is the module key; `api` is null.
- `evidence`: one or more classes or `Class#method` (binary names, `$` for nested types) where the behaviour
  is implemented: the plugin jar, its internal libraries or the API jar. Harness-side only, never shown to
  the implementer, so internal names are fine here. A claim about a constant cites its class.
- `confidence`: `high` = read in the code with its edge cases; `medium` = clear, but an edge depends on code
  you could not fully follow (or on Jira at run time); `low` = inferred.
- Keys are permanent ids once built. Make them descriptive and stable.

## What a good claim is
- **Observable from outside the module:** through its exported interface (the methods in API.md): inputs →
  results, which `StructureException`/error code (by its public `StructureErrors` name) and when, nulls,
  defaults, ordering, permission checks (who may do what, and what an unauthorised caller sees: an error,
  an empty result, a filtered list), what is stored (which Active Objects table and columns, which property
  keys, in SPEC.md's names), when changes become visible (caching, invalidation, events it publishes or
  listens to), what it does with the Jira services it is given, lifecycle (start, stop, what happens before
  the plugin is ready). Thread-safety only where the code makes it explicit.
- **Specific enough to write a JUnit test from** with mocked Jira services. Concrete values and edge cases,
  e.g. "`getStructure` of an id that does not exist throws a `StructureException` with error
  `STRUCTURE_NOT_EXISTS_OR_NOT_ACCESSIBLE`; so does an existing structure the user may not view".
- **Your own words, behaviour only.** No code, no pseudo-code transcribing method bodies, no internal
  algorithms that are not observable. Never copy javadoc phrasing.
- **No internal class names** in `behaviour`: use module keys, public API type names (anything in API.md),
  Jira and JDK types, third-party library types, and the SPEC.md contract names (tables, columns, property
  keys, REST paths). For internals, describe the effect. The validator flags names that must be rephrased.
- **Uniformly deep.** Every module gets claims for each method (or group of related methods) of its exported
  interfaces: normal case, boundaries, errors, permissions, nulls, persistence. Typical: 3–8 claims for a
  small component, 15–40 for a large one (a structure manager or a sync manager may need more). Don't pad,
  and don't skip methods: note in your report any interface method you could not claim.
- **Delegation:** a thin component that forwards to internal code is still claimed by what the caller sees.
  Follow the delegation as far as needed to state it; claim the observable result, not the path.
- **Describe the original faithfully, bugs included.** Where it looks like a bug, state what it does, add
  "(as the original does)" and list it in your report. Prefer `medium` if unsure it is intended. That exact
  phrase flags the claim `suspected_bug` for the implementer, who must check it; use it only for suspected bugs.
- **Java assertions.** Where the original checks something only with `assert`, state both outcomes:
  "with assertions enabled (as the tests run) it throws `AssertionError`; with them disabled, …".
- **Behaviour that needs a running Jira** (i18n texts, the current user, Jira permission and component
  lookups, cluster locks, scheduler) still gets a claim, stated as what the module asks Jira and what it does
  with the answer. Say what is not determinable rather than invent it.
- **Out of scope:** anything that contacts the vendor or the Marketplace, and **all licence checking** (owner,
  2026-10-28: the replacement has no licence checking at all). Do not describe the original's licence logic.
  Where a module exposes a licence state, claim the fixed answer ("licensed, valid, not expiring", never
  blocked or read-only). Check SPEC.md §1.1 and §1.8 for the exact rule.

## Validate before you finish
    .venv/bin/python fixtures/tasks/jira_re/analyst/build_claims.py --validate fixtures/tasks/jira_re/analyst/claim-notes/<group>.json
It must print `ok`. It catches unknown modules, bad evidence and leaked internal names. Do **not** run
`build_claims.py` without `--validate`, and don't run `check_spec.py`, `build_api.py`, `prepare_seed.py` or
anything that writes: other helpers are working in parallel.

## Report (your final message, short)
- claims written per module; interface methods left unclaimed, if any;
- suspected bugs in the original (module, behaviour);
- disagreements with API.md or SPEC.md (where, what is wrong);
- behaviours you could not determine;
- anything you read in `dropped-throws.txt` classes that changed a claim.
