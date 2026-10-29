# Phase JC1: claims session 1, the public Java API (jira-re)

**Date:** 2026-10-28 · **Branch:** `jira-re` · **Design:** `docs/jira-re-design.md` §7.2, §7.4 · **Previous:** JS3

The first claims session. It built the claims tooling and wrote the claims for the public Java API's own code,
so that all 51 API tests rest on claims. No API spend.

**Exit check (stated at the start):**
1. **Claim schema.** An API claim has `"api"` (a top-level API type) and `"module": null`, and every claim has
   exactly one of the two. `check_spec` rejects an unknown `api` type, wants an active claim for every API type
   that carries code, and lets evidence cite the API jar.
2. **`analyst/build_claims.py`, tests first.** Notes in, claims and evidence out, permanent ids
   (`analyst/claim-ids.json`). A dropped key fails unless the claim is retracted. Leaks and evidence that does
   not resolve fail the build. It has a `--check` mode.
3. **Content.** All 268 code-carrying API types are claimed, and all 51 API tests are mapped.
4. Stage 4 and the spec README say how API claims are tested.
5. No leaks, and no copying from the vendor's javadoc.
6. `pytest` and `-m local` are green, and the seed is re-pinned.

**Result: met.** `check_spec`:
- 999 claims;
- API types with code: 268 of 268 claimed;
- API tests: 51 of 51 backed by claims;
- 609 problems, down from 662. They are:
  - the module claims (608, the next sessions);
  - the change-request placeholder.

JS3 was committed first, as `d5e62b3`, at the owner's request.

## What was built

**`analyst/build_claims.py`:**
- **Inputs and outputs.** It reads `analyst/claim-notes/*.json` in file-name order. Each claim there has a stable
  `key`, its owner (`module` or `api`), `behaviour`, `confidence`, an optional `status`, and `evidence`. It
  writes:
  - `spec/claims.jsonl`, sorted by id, with no keys and no evidence;
  - `analyst/claims-evidence.jsonl`, which holds the id, key and evidence;
  - `analyst/api-test-claims.json`, from the notes' optional `tests` section (test id → claim keys), written
    with ids.
- **Ids.** They are permanent. `analyst/claim-ids.json` maps every key ever built to its id, and a new key gets
  the next free id.
- **Failures.** The build fails on any of these:
  - a key that disappears (mark the claim `retracted` instead);
  - a duplicate key, an unknown field, or an empty behaviour;
  - a bad confidence or status;
  - neither or both of `module` and `api`, or an unknown module or API type;
  - evidence that does not resolve;
  - an internal class name in a behaviour (dotted, or a CamelCase simple name), unless it is in
    `contract-classes.txt`;
  - a test mapped to an unknown key.
- **Modes.** `--check`, plus `--validate FILE`, which checks one notes file and writes nothing (for helpers
  working in parallel).

**`hidden/_support.reference(..., extra_jars=)`** adds standalone jars, so evidence can cite the API jar.

**`check_spec.py`:**
- A claim belongs to exactly one module or one public top-level API type.
- `api_code_types()` lists the public top-level API types whose class files, member types included, have a
  method body other than a static initialiser: 268 of 417. Each needs an active claim.
- Pure interfaces and annotations (149) are left to the claims of the modules that implement them, although a
  claim may still name one. Two do: `Forest` and `EffectorProcess`.
- Evidence resolves against the plugin jar, its internal libraries and the API jar.
- The report adds the line "API types with code N: claimed M".

**Implementer text:**
- `spec/README.md` and SPEC.md's reading guide explain the `api` field.
- `stage4.md` now asks for a JUnit test named after each active API claim, the rule stage 2 already sets for
  module claims. This is a task-text change, not a D-n change.

**The claims** were written by nine helper agents, one per JS3 package group, under the JS1–JS3 clean-room
rules (shared brief: behaviour only, own words, no `central-src/`). Each helper had its own scratch folder,
the fix proposed in JS3. Each wrote one notes file and checked it with `--validate`. The helpers with tests
mapped them, writing a claim for any assertion no claim stated yet.

| group | claims | types | tests |
|---|---|---|---|
| g1-core | 104 | 26 | 0 |
| g2-loaders | 167 | 56 | 0 |
| g3-effects | 66 | 25 | 1 |
| g4-forest | 82 | 23 | 0 |
| g5-generators | 83 | 21 (+ `Forest`) | 24 |
| g6-items | 89 | 24 | 15 |
| g7-rows | 110 | 39 | 1 |
| g8-structures | 128 | 24 | 0 |
| g9-util | 170 | 30 | 10 |

Confidence: 883 high, 114 medium, 2 low. The median claim is 302 characters long. The longest are constant
tables, for example every `StructureErrors` code with its category. g1-core confirmed exact messages and text
formats by running the real API jar in its scratch folder.

**What I checked afterwards:**
- **Leak scan** (`check_spec`): clean.
- **Copying:** I compared 8-word sequences with the vendor's javadoc (71,288 sequences). 3 claims match, all on
  stock phrases ("if the row is not in the forest").
- **Quality:** I read a random sample. The claims give concrete values, exact text forms and error paths, and
  each one can be turned into a test.
- **Dropped throws in the decompiler (new check).** Three helpers found that Vineflower had silently dropped a
  `throw` (in `SourceOfTruth.fromCode`, `SyncLogger.get` and `AttributeValue.getDefinedValue`). I compared every
  API class's bytecode throws (`new X … athrow`, leaving out `AssertionError` and rethrows) with the `throw`
  statements in its decompiled source. Of 288 throw instructions, 4 are missing in the source: the three above
  and `AttributeLoaderBuilder.notNull`. API.md describes all four correctly (the JS3 helpers had used `javap`).
  The same scan should be run on the plugin's own classes before the module claims.

**API.md corrections.** The helpers found 21 places where API.md was wrong or incomplete. I fixed them in
`api-notes/` and rebuilt API.md:
- `HistoryQuery`: null author or ancestor elements throw; API.md said they were ignored.
- `ArrayForest.getChildrenIndicesIterator`: only -1 means the roots.
- `ArrayForest.replaceSubtrees`: it fails halfway on an immutable forest that needs a merge.
- `StructureRows.makeShallow`: throws for row 0 and the super-root.
- `ForestSpec.Builder.build`: built specs share the builder's list of transformations.
- `ForestChange`: an immutable target throws; `Reorder` error cases; the nested classes can be subclassed.
- `ItemIdentity.longId` and `stringId`: a null or blank type is checked only by an assertion.
- `DarkFeatures`: system properties are decoded the way `Long.getLong` does (`0x10`, `010`); an empty system
  property counts as set.
- `AttributeSpecNormalization`: key order and plain nested maps.
- `SimpleDerivedAttributeLoader.idLoader`: formats are compared by identity.
- `ReductionStrategy.apply`.
- `ViewSettings.AssociatedView.Builder.setMenuPages`: an empty result after filtering.
- `SyncAuditLogHelper`: a null owner key throws.
- `SimpleRow.getItem`: the garbled sentence is fixed.
- `ComparableTuple.of(String[])`: what null elements do.

## Tested

- New `tests/unit/test_jira_re_claims.py`, 20 tests, written before `build_claims.py`:
  - ids in order and permanent;
  - retracted, never dropped;
  - every rejection rule, one case each;
  - allowed names and duplicate keys;
  - notes merging;
  - the test mapping;
  - determinism.
- `test_jira_re_fixtures.py`: 2 new check_spec tests:
  - the API claim coverage and evidence in the API jar;
  - one owner per claim.

  `_mini_class` can now emit a method with a body.
- `test_jira_re_api_doc.py`: its problem filter now leaves out claim problems.
- `pytest`: 1,734 passed, 1 skipped.
- jira-re `-m local`: 3 passed.
- `build_claims --check`, `build_api --check`, `build_contract --check` and `prepare_seed --check` are all up
  to date.
- Seed re-pinned: `7f1b2c5d…`.

## Unresolved, and proposals

1. **Java assertions.** The original checks some inputs only with `assert`. Surefire runs tests with
   assertions on (the default; the seed's pom does not change it), so the hidden tests see `AssertionError`.
   19 claims state both outcomes, assertions on and off. A rewrite can match both with an `assert` of its own.
   **Proposal:** keep this as the rule for claims; the owner may prefer "invalid input, any exception" instead.
2. **Suspected bugs in the original,** stated as they are and marked "(as the original does)". As in JS3, the
   claims sessions and `CHANGES-1.md` decide what stays contract. The main ones:
   - **Immutability leaks:**
     - `ForestSpec.Builder` shares its transformations list with the specs it builds;
     - `ViewSpecification.Builder` shares its pin list;
     - `ForestAction.Move` and `Remove` keep the caller's list;
     - `HistoryEntry` and `SyncAuditLog.ActionGroup` expose the caller's lists;
     - `ImmutableItemForest.of(row)` and `copySubtree` are not immutable;
     - `ArrayForest.set` and `replaceSubtrees*` skip the immutability check, so `Forest.EMPTY` can be changed;
     - `ProcessDisplayParameters.Builder.build()` returns the builder's own instance;
     - `AttributeSpec`'s parameter map can be changed after the spec is created, leaving its cached text stale.
   - **Contract violations:**
     - `ComparableTuple` with NaN breaks the `Comparable` contract;
     - `ItemIdentitySet.containsAll` compares sizes first;
     - `TrailItemSet.of(null, x)` holds null;
     - a `PermissionRule.SetLevel` with `EDIT_GENERATORS` decodes as `AUTOMATE`;
     - not-null declarations that return null: `LicenseData.Disabled(null)`, `SyncAuditLog.ActionGroup`,
       `CoreIdentities.option`.
   - **Error paths:**
     - `ArrayForest.getSubtreeEnd(size())` throws index-out-of-bounds;
     - `replaceSubtrees` leaves a forest half changed;
     - `SimpleRow.getItem` and `StructureUtil.memoize` return null for ever after a single failure;
     - `ForestChange.Move` with a missing row puts the next row first;
     - `SyncLogger.warnStructureException` logs its prefix twice;
     - `CoreEffects.setNumberCustomField` does not convert `Float`, `Short` or `Byte`;
     - `AbstractScanningLoader` drops an error carried on the preceding row;
     - single-row loaders adapted to propagate do not forward `preload`;
     - several `toString`, `equals` and `hashCode` methods throw `NullPointerException` on null fields.

   Two such null paths have no claim: `StructureException.asI18nText` with null parameters, and
   `CoreEffects.emitWarning` with an `I18nText` whose arguments are null.
3. **Claims that need a running Jira (114 medium).** Some behaviour goes through Jira services: i18n, the current
   user, permission and component lookups, and the plugin's implementations of service interfaces. Those claims
   say what the API does with what it is given. Hidden tests for them need mocks. Claims sessions on the owning
   modules should settle them.
4. **Not determined.** For example:
   - the `StructureException` details text when there is no plain message, inside Jira;
   - the `mergeForest` order in general, when rows are shared;
   - the build order of `ItemForestBuilderImpl`;
   - what happens with repeated values in `LongListHashIndex` (the last one is inferred to win);
   - `MapObject` behaviour that depends on the `org.json` version.

   The helpers chose `medium` or `low` for these, never a guess at `high`.
5. **Static fields as evidence.** `resolve` only knows methods, so a claim about a constant cites its class.
   This is good enough for grounding. **Proposal:** leave it.
6. **Clean-room near miss.** One helper's text search over the whole `analyst-work/` tree printed three lines of
   `central-src/` (one call, identical to the decompiled code). Nothing was used and no file was opened. The
   next brief will tell helpers to keep `central-src/` out of searches.
7. **New hidden API behaviour tests** were not written in this session; the 51 existing ones are now mapped.
   **Next:** write tests from the API claims (in particular the types with no test yet), re-run
   `selfcheck_api.py`, then `gen_visible_api_tests.py` and `prepare_seed.py`.
8. The owner questions from JS3 are still open: `GenericItemHistoryManager` as contract, the API permission gaps
   for `CHANGES-1.md`, and the licence type.

No spec decision (D-n) was changed.

## Next session

Module claims (608 modules, 14–24 sessions). Start with the components that implement the API's service
interfaces, so the pure interfaces' behaviour is claimed through their modules. Run the dropped-throw scan on the
plugin's classes first. Write the notes in `analyst/claim-notes/`, then run `build_claims.py`, `check_spec.py`
and `prepare_seed.py`.
