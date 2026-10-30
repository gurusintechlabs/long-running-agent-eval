# JC5 helper brief: behavioural claims for the plugin's REST, pages, filters and Jira hooks

Repo: /Users/tonylee/Documents/coding/longhorizon_testing (branch jira-re). You are an analyst helper in a
clean-room reverse-engineering project. Another engineer (an AI agent) will re-implement this Jira plugin
**from our spec alone** and never sees the original code. You write **claims**: one testable behaviour per
claim, in your own words. The implementer writes a JUnit test per claim (named after the claim id) against its
own code, and hidden tests check the re-implementation against them.

This session covers the plugin's **non-UI surface modules**: the three REST modules, the webwork pages, the
servlet filters and servlet, and the modules that hook into Jira (JQL function, custom field type and searcher,
workflow condition and validator, activity stream, user handlers, link factories, transformer, `ao`, Velocity
allowlists). The API types (JC1), all 211 components (JC2, JC3) and the 234 extension modules (JC4) are already
claimed. Most of what these modules do is delegation to those: build on them, and refer to them by module key.

## What is contract for these modules
- **The module key, type and descriptor element** (attributes and children; `inventory.json` under `contract`).
- **Your scope.** `scope.txt` in your scratch folder lists the original's source files you own, and the REST
  endpoints or webwork aliases they serve. Several helpers share `rest-v1`, `rest-v2` and `ww-structure`.
  **Every endpoint and every alias and command in your scope must appear, written exactly, in at least one
  claim.** This is checked by script.
- *REST endpoint.* SPEC.md §1.3 already gives each endpoint's path, parameters, shapes and main errors, and the
  conventions (access gate, error formats, headers). Don't restate them. Claims add what a test needs beyond
  them, in the form `` `GET /rest/structure/2.0/x`: given ..., it ... ``: the permission rule for each action, what is
  checked in what order, defaults and clamps, the order and limits of results, how each input edge case
  answers (missing, null, unknown id, no access, archived, anonymous), what is changed or stored, and what an
  unknown value does. **Read the SPEC.md entry of every endpoint against the code and report each mismatch.**
  Name shapes by their SPEC.md names. A trivial endpoint that SPEC.md covers fully gets one claim.
- *Webwork page.* The URL `/secure/<alias>.jspa`, `/secure/<alias>!<command>.jspa` and `/secure/admin/...` is
  contract; the action classes, their result names and the template paths are not. SPEC.md §1.4 says "What each
  page shows and does is described in the claims", so claim per alias and command: its request parameters
  (exact names, defaults, parsing), who may open it and what others get, what it does on GET and on submit,
  what it changes and stores, where it redirects, its validation errors (i18n key and English text), and which
  data the page presents, as a list of facts. Don't describe HTML, CSS or JavaScript: the next session does.
- *Servlet filter or servlet.* The location, weight and URL patterns are contract. Claim which requests it acts
  on, what it does to them (request, response, headers, cookies, page resources), what it records or tells
  the rest of the plugin, and what it does when it fails or when the other app is absent. It never breaks the
  request it filters unless the code says so.
- *Jira hook.* Whatever Jira stores or calls is contract: workflow descriptor argument names and values, the
  custom field's key and persisted config, JQL function name, argument forms, validation messages and result,
  stream entries, and the handler results Jira shows. Say what each Jira callback gets and returns.
- *Velocity allowlist.* Only the key and type are contract. The listed classes and methods are the original's
  and are not named in claims: the implementer's allowlist lists its own getters. Claim which page family the
  module serves, and what must hold: every method those pages' templates call is listed, and anything else
  stays uncallable. Add a small summary of the kinds of values those pages read, and report any listed method
  that changes state.
- **Licence and vendor rules apply here too** (see Out of scope below). Licence pages, banners and endpoints get
  the fixed answer only. Do not read or describe licence, certificate, serial or Marketplace logic.
- The implementing classes, their helpers and their method shapes are **not** contract: never name them.

Jira version: the pinned platform is **Jira 9.12**. Where a module has several classes for different Jira
ranges (`...J9` / `...J10` / `...J11`, javax / jakarta), claim the Jira 9 one only. Integrations (Jira
Software, Advanced Roadmaps, Tempo, Assets, Service Management, ScriptRunner) are claimed for when the other
app is present and for when it is absent.

## Your inputs
- Your modules: `modules.txt` in your own scratch folder (path in your prompt): module key, its descriptor
  element(s), the original's implementing class (internal, never name it in a claim) with the path of its
  decompiled source, purpose from the inventory, related modules, SPEC.md lines and existing claim ids that
  mention the key. `scope.txt` beside it: see above.
- The descriptor itself, the Velocity templates and the i18n bundle are in `analyst-work/jar/`
  (`atlassian-plugin.xml`, `templates/`, `i18n/StructureMessages.properties`). Read a generator's form and
  summary templates for its parameter names, but claim parameters from the Java code that reads them.
- Decompiled source (Vineflower): the plugin in `analyst-work/vf/`, its internal libraries in
  `analyst-work/libvf/<lib>/` (much real logic lives in structure-commons), the public API in
  `analyst-work/apivf/`. Class files: `analyst-work/jar/` (plugin), `analyst-work/apijar/` (API), the libraries
  as jars in `analyst-work/jar/META-INF/lib/`. Tools: `~/lrae-tools/re/bin/javap` (`javap -c -p -cp DIR CLASS`).
- **The decompiler drops some `throw`s.** `fixtures/tasks/jira_re/analyst/dropped-throws.txt` lists every class
  where the bytecode throws more than the source shows, including exceptions built by a method call (listed as
  `name()`). For those classes, and wherever an error path matters and looks odd, read the method with
  `javap -c -p`. A method that seems to return null where the API says not-null is such a case.
- The spec already written, which your claims must agree with:
  - `fixtures/seed_jira_re/spec/API.md`: every API type and member, with a one-line meaning. Search
    `### \`<fq type>\``. Your module's interfaces are there.
  - `fixtures/seed_jira_re/spec/SPEC.md` Part 1: module table (§1.2), REST (§1.3), Active Objects tables and
    columns (§1.5), persisted names such as property keys (§1.6), and §1.8 (out of scope: contacting the
    vendor; the replacement never phones home, and no Marketplace licensing: every licence check behaves as
    licensed and valid).
  - `fixtures/seed_jira_re/spec/claims.jsonl`: existing claims (API types, public and internal components).
    Do not repeat them; build on them. Search it for your module key and for the API interfaces you implement
    (`"api": "<fq type>"`).
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
- **Observable at the module's boundary, without prescribing its shape.** State the behaviour as
  "given this situation / input, the module does / returns / stores / asks Jira for ...". Good subjects:
  results and their order, defaults, limits and sizes (cache sizes, expiry times, batch sizes, thresholds,
  stated with their numbers), validation and errors (by public `StructureErrors` name or a JDK/Jira exception
  type where callers see it), permission rules (who gets what, and what an unauthorised user sees), what is
  stored (Active Objects tables and columns, property keys, in SPEC.md's names), when changes become visible
  (caching, invalidation, events published or listened to), what it does with the Jira services it uses,
  lifecycle (start, stop, before the plugin is ready), and how its work shows through REST (SPEC.md §1.3) or
  the public API. Thread-safety only where the code makes it explicit.
- **Specific enough to write a JUnit test from** with mocked Jira services, against an implementation whose
  method names you do not know. Concrete values and edge cases: "an avatar's HTML is reused for 5 minutes,
  then rendered again"; "a permission level computed for a user is reused until a structure's permissions
  change or 30 s pass"; "a search for a display name matches it exactly, ignoring case, across all user
  directories; inactive users are skipped".
- **Your own words, behaviour only.** No code, no pseudo-code transcribing method bodies, no internal
  algorithms that are not observable, **no internal method or class names**. Never copy javadoc phrasing.
- **No internal class names** in `behaviour`: use module keys, public API type names (anything in API.md),
  Jira and JDK types, third-party library types, and the SPEC.md contract names (tables, columns, property
  keys, REST paths). For internals, describe the effect. The validator flags names that must be rephrased.
- **Uniformly deep.** Every module gets claims covering each responsibility: normal case, boundaries,
  errors, permissions, nulls, persistence. Typical: 2–5 claims for a thin bridge or holder, 4–10 for a cache,
  store or helper, 15–40 for a large one (a formula function library, an event bridge, a permissions
  calculator, a synchronizer, a field grouper). For this session: 1–4 per ordinary REST endpoint, 3–10 per
  webwork page, more for the large ones (forest update, poll, item create, copy, restore). Don't pad, and don't
  skip responsibilities.
- **Big catalogues** (a formula function library, a field catalogue, a set of statistics): one claim per
  function or entry, or per small family of them, with argument rules, results, edge values and error
  results. Completeness matters more than brevity here: the implementer has nothing else to go on.
- **Thin bridges and holders** (version adapters, static access points, Jira service bundles): claim what
  they report or do on Jira 9.12 and their fallbacks (what happens when the Jira service is missing or
  throws). If a module really carries no behaviour of its own, write one claim stating what it provides and
  to whom, and say so in your report.
- **Delegation:** a module that forwards to another is still claimed by what the caller sees. Follow it
  as far as needed; claim the observable result, not the path. If the behaviour belongs to a module that
  already has claims (claims.jsonl), refer to that module by key instead of restating it.
- **Describe the original faithfully, bugs included.** Where it looks like a bug, state what it does, add
  "(as the original does)" and list it in your report. Prefer `medium` if unsure it is intended. That exact
  phrase flags the claim `suspected_bug` for the implementer, who must check it; use it only for suspected bugs.
- **Java assertions.** Where the original checks something only with `assert`, state both outcomes:
  "with assertions enabled (as the tests run) it throws `AssertionError`; with them disabled, ...".
- **Behaviour that needs a running Jira** (i18n texts, the current user, Jira permission and component
  lookups, cluster locks, scheduler, the issue index) still gets a claim, stated as what the module asks Jira
  and what it does with the answer. Say what is not determinable rather than invent it.
- **Out of scope:** anything that contacts the vendor or the Marketplace, and **all licence checking** (owner,
  2026-10-28/29: the replacement has no licence checking at all, and the claims never describe the
  original's licence logic, certificates or serial checks). Where a module exposes a licence state, claim the
  fixed answer ("licensed, valid, not expiring", never blocked or read-only). Modules that only contact the
  vendor keep their keys and do nothing outward: claim exactly that (no network traffic, what they report
  locally). Check SPEC.md §1.1 and §1.8 and INVENTORY.md §5 for the exact rules, and follow them over the code.

## Validate before you finish
    .venv/bin/python fixtures/tasks/jira_re/analyst/build_claims.py --validate fixtures/tasks/jira_re/analyst/claim-notes/<group>.json
It must print `ok`. It catches unknown modules, bad evidence and leaked internal names. Do **not** run
`build_claims.py` without `--validate`, and don't run `check_spec.py`, `build_api.py`, `prepare_seed.py` or
anything that writes: other helpers are working in parallel.

## Report (your final message, short)
- claims written per module; responsibilities left unclaimed, and modules with no behaviour of their own, if any;
- suspected bugs in the original (module, behaviour);
- disagreements with API.md or SPEC.md (where, what is wrong);
- behaviours you could not determine;
- anything you read in `dropped-throws.txt` classes that changed a claim;
- endpoints, aliases or commands in your scope that you left without a claim (there should be none).
