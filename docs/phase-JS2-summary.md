# Phase JS2: analyst spec session 2, the external contract (jira-re)

**Date:** 2026-10-28 · **Branch:** `jira-re` · **Design:** `docs/jira-re-design.md` §7.2 · **Previous:** JS1

The second analyst session. It wrote Part 1 of `spec/SPEC.md`, the external contract, everything except the
public Java API types (Part 2, the next sessions). No API spend.

**Exit check (stated at the start):**
- `check_spec.py` has new rules, written tests first: SPEC.md lists every module with its type; every REST
  endpoint of the pinned Jira 9.12, read from bytecode, has its own heading and a description; every AO table
  and column appears.
- No problems from those rules and no leaks.
- SPEC.md Part 1 is written: identity and OSGi, modules, REST (endpoints, parameters, payload shapes,
  conventions), servlets, filters and pages, stored data, other persisted names, front-end hooks, out of
  scope.
- `pytest` is green and the seed is re-pinned.

**Result: met.** `check_spec`:
- 163 of 163 REST endpoints described;
- 186 of 186 AO columns specified;
- 1,075 problems, down from 1,079. None are contract or leak problems. They are claims (608), API types not
  yet specified (413), the API-test mapping (51), the missing `claims.jsonl` and `claims-evidence.jsonl`, and
  the change-request placeholder.

## What was built

**Extraction from bytecode (pure Python, harness-side):**
- `hidden/_classfile.py` decodes runtime-visible annotations on classes, members and parameters.
- New `hidden/_contract.py` reads three things:
  - **REST endpoints** of the `<rest>` modules that apply to the pinned Jira. Per endpoint: method, full path,
    media types, parameters (kind, name, JSON type from the generic signature, default) and security
    annotations. Inherited resource methods and sub-resource locators are followed, as JAX-RS does.
  - **AO schema:** prefix by the MD5 rule; every column's name, type, length and constraints.
  - **JSON shapes** by Jackson's rules: public fields and getters, `@JsonProperty` renames and annotated
    setters, `@JsonIgnore`. An explicit `@JsonProperty` beats `@JsonIgnore` on another accessor.
- It lives in `hidden/`, so a later contract tier can test the rewrite with it.
- `applies` (the `<restrict>` check) moved there from `build_inventory.py`.

**For Jira 9.12 it finds:**
- 163 endpoints: `rest-v1` 44, `rest-v2` 115, `rest-cfd` 4;
- 39 tables with 186 columns. Every column name is declared explicitly, so nothing depends on AO's naming
  rules;
- 200 payload shapes.

**`analyst/build_contract.py`** splices generated blocks into SPEC.md between markers:
- the blocks are the module table, REST conventions, endpoints, shapes, AO tables and persisted names;
- its input is the analyst's notes in `analyst/contract-notes/*.json` (harness-side);
- notes name a payload class only as `{{fq.Class}}`, which renders as its own-words shape name with a link;
- the build fails on:
  - stale notes (unknown endpoint, field, column or class);
  - duplicate shape names;
  - any internal class name in the output, unless `contract-classes.txt` lists it;
- missing notes render as `(not yet described)`, which `check_spec` reports;
- `--check` reports whether SPEC.md is stale.

**`check_spec.py`, new rules:**
- module table rows (`| key | type |`);
- endpoint headings and their descriptions;
- AO tables and columns;
- any other pending description;
- the Jira version comes from the seed pom.

**SPEC.md Part 1** (6,700 lines, 512 KB). It has these sections:
- §1.1 identity and OSGi: the owner's three decisions below;
- §1.2 modules (generated table); module types and module keys as stored data;
- §1.3 REST: conventions, then 163 endpoints and 200 shapes, each with a summary, parameter meanings,
  request, response and errors. Formats are given precisely enough to build and parse: the forest encoding,
  incremental updates, versions, attribute values, async jobs;
- §1.4 the webwork pages, the Excel servlet (parameters, content types, filename rule, statuses) and the
  eight filters;
- §1.5 AO: intro, then 39 tables, each with a summary and the meaning and stored format of every column;
- §1.6 other persisted names:
  - workflow class and arguments;
  - JQL function, custom field keys, gadget spec URIs and user preferences;
  - property keys, chunked application properties, the build marker and backup formats, from the notes;
- §1.7 front-end extension points;
- §1.8 out of scope: contacting the vendor, now also the about popup's Marketplace check.

The notes were written by four helper agents, under the JS1 clean-room rules:
- A: `rest-v1`, `rest-cfd` and the REST conventions;
- B: the forest, structure, attribute, item and effect half of `rest-v2`;
- C: the configuration, saved-column, note, picker and miscellaneous half of `rest-v2`;
- D: the AO tables and other persisted names.

I then:
- merged their notes;
- fixed the extractor gap A found (an ignored field with an explicit accessor);
- filled the one meaning that gap exposed;
- removed a duplicated "Body:" line;
- aligned the statistics endpoint with the out-of-scope ruling;
- audited links (none broken) and the leak scan (clean).

## Owner decisions (2026-10-28, also in design §8)

1. **No Marketplace licensing.** The replacement omits `atlassian-licensing-enabled`, and every licence check
   behaves as "licensed, valid".
2. **OSGi exports:** only the API packages (17.26.13) and `com.almworks.integers*` (1.1.3). The original's
   internal packages (`structure.util`, `rest2g`), POI and the annotations library are not contract.
3. **Identity:** the plugin key and bundle symbolic name are kept. The display name, vendor, version and icons
   are the implementer's own.

## Tested

- New `tests/unit/test_jira_re_contract.py`, 16 tests, against classes compiled by javac from stubs:
  - annotation decoding;
  - REST extraction: inheritance, sub-resources, scanned packages only, method overrides class media types,
    `@Context` dropped, generic body type;
  - `<restrict>` selection of rest modules;
  - the AO prefix (`AO_8BAD1B`), schema and constraints;
  - Jackson visibility and the explicit-beats-ignore rule;
  - shape closure;
  - check_spec's new rules, including pending descriptions;
  - `build_contract`: rendering without class names, determinism, stale notes rejected, notes merging.
- The JS1 fixture SPEC.md gained a module table.
- `pytest`: 1,697 passed, 1 skipped.
- jira-re `-m local`: 3 passed.
- `build_contract --check`, `build_inventory --check` and `prepare_seed --check` are all up to date.
- Seed re-pinned: `dd340d21…`.

## Unresolved, and proposals

1. **Cloud migration hands data to Atlassian.** On an admin-started cloud migration, the original passes a
   zip of its data to Jira's Cloud Migration Assistant, which uploads it to Atlassian. That is neither the
   vendor nor the Marketplace, so §1.8 now says "no connection of its own accord", and SPEC.md describes the
   hand-off as the original does it. **Owner: keep it, or put it out of scope too?**
2. **Weak permission checks in the original.** The spec describes them faithfully:
   - `POST /synchronizers/undo` adds or removes issue links and epic or rank changes for any user who may
     use the plugin;
   - `GET /create-structure/versions` lists any project's versions;
   - `GET /note/{id}` and `GET /perspective/{id}` read any note or perspective by id;
   - `GET /sjqlTroubleshooting/logs` (no admin needed) may include other users' query traces.

   **Proposal:** keep the paths and payloads, but let the owner decide per item whether the replacement
   tightens the check. That would go into `CHANGES-1.md`, not a silent spec change.
3. **Bugs in the original.** Examples: history writes `direction` but reads only `moveDirection`; CFD
   messages are swapped; undo always reports one success. The spec says "write the original form, accept
   both" where data is involved. Claims sessions should decide the rest.
4. **The decompiler drops branches.** Agent C found null checks that throw (and their 400 replies) in the
   bytecode that Vineflower left out. **Proposal:** claims sessions confirm error paths with `javap -c` or
   CFR, not Vineflower alone.
5. **Not determined; needs a live check or deeper reading:**
   - `rest-cfd` error statuses: probably the platform's 500, because no mapper is installed;
   - the absolute `Location` header of `POST /structure`;
   - `GET /manage-structures/one` without `id`;
   - units of generator health times and of the attribute time and duration formats;
   - `/note` with a null `name`.
6. **Shape names.** 24 of the 200 own-words names equal a kebab-cased class name, for example `poll-request`
   and `saved-column`. Two of them are public API types. They are plain domain words, so I kept them. The
   leak scan does not look at kebab case.
7. **Not contract (proposed):**
   - dark-feature tuning keys whose prefix is an internal class name;
   - a lock name that looks like a class name.

   SPEC.md describes both without the class names.
8. **The exported non-API interface** `GenericItemHistoryManager` needs its signatures in Part 2 (from JS1).
9. **The browser-side API** that companion apps call is not specified yet. §1.7 defers it to the
   web-resource claims.
10. **SPEC.md is 512 KB.** The implementer reads it in parts, by heading. **Proposal:** if the pilot shows
    context trouble, split REST and AO into separate files; `build_contract` already works by block.
11. **Proposal (P(t) change, so for the owner):** a hidden contract tier. It would use `_contract.py` to
    check that the rewrite has every endpoint (method and path) and every AO table and column, scored per
    module like t04.

No spec decision (D-n) was changed.

## Next session

Part 2: the 417 public API types and their signatures, in my own words (3–5 sessions), plus
`GenericItemHistoryManager`. Then the claims sessions. Re-run `build_contract.py` whenever the notes change,
and `prepare_seed.py` whenever `spec/` changes.
