# Phase JC2: claims session 2, the public service components (jira-re)

**Date:** 2026-10-28 · **Branch:** `jira-re` · **Design:** `docs/jira-re-design.md` §7.2, §7.4 · **Previous:** JC1

The first module-claims session. It applied the JC1 proposals the owner accepted, added a scan for throws the
decompiler drops, and wrote the claims for the 45 public components: the modules that implement the API's
service interfaces, so the pure API interfaces now have behaviour claimed through their modules. No API spend.

**Exit check (stated at the start):**
1. **Accepted JC1 proposals recorded.**
   - Assertion rule: claims state both outcomes, and `spec/README.md` tells the implementer that tests run
     with assertions on.
   - Constants are cited by their class.
   - Helper briefs keep `central-src/` out of every search.
2. **Dropped-throw scan, tests first,** run on the API, the plugin and the internal libraries. Its output is
   given to the helpers.
3. **Content.** All 45 public components have active claims, and every method of their exported interfaces
   is claimed.
4. **Leaks and copying.** No leaks and no copying from the vendor's javadoc. Spec errors the helpers found are
   fixed in the notes, and API.md and SPEC.md are rebuilt.
5. **Green.** `pytest` and `-m local` pass, all `--check` modes are up to date, and the seed is re-pinned.

**Result: met.**

`check_spec`:
- 1,608 claims (609 new);
- modules with an active claim: 45 of 608;
- 564 problems: the 563 modules still to claim, plus the change-request placeholder.

## What was built

**`analyst/scan_throws.py`** (new, analyst-side):
- For each top-level class, it compares the exceptions the bytecode constructs and throws with the `throw`
  statements in the Vineflower source. The bytecode side is read from `javap -c -p` (`new T … T.<init>;
  athrow`), with inner classes and lambdas included.
- It skips rethrows, exceptions built by a helper method (static, or private through `invokespecial`),
  assertions and compiler-made throws.
- It reproduces JC1's four API drops exactly.
- Its output is `analyst/dropped-throws.txt`:
  - API: 4;
  - plugin: 17 classes;
  - internal libraries: 6 classes.

  A spot check confirmed `StructureConfigurationImpl` (dropped `IllegalArgumentException("Unknown
  permission: …")`).
- **It paid off three times:** API.md was wrong about `StructureConfiguration`'s unknown-permission error,
  about `StructureJobManager.execute` with an unknown executor, and it did not mention
  `backupToStream(null)`.

**Stricter leak scan.** `check_spec.CAMEL` now also matches simple names that start with an acronym
(`AOBasedStructureManager`). `build_claims` imports the same pattern instead of keeping a copy.
- **What it caught:** a helper had named a dark-feature key prefixed with an internal class name. Its package
  was an old one, so it matched no class exactly, and `AO…` defeated the old pattern. SPEC §1.6 already says
  those keys are not contract, so the three claims were reworded.
- **One old hit in SPEC.md:** the cluster lock name `com.almworks.structure..AOLock.<id>`. Lock names are
  contract (§1.6, mixed nodes during an upgrade), so the word `AOLock` is now allowed in
  `contract-classes.txt`, as the webwork aliases are.

**The claims** were written by nine helper agents, each with its own scratch folder, under the JC1 rules
plus a module brief. The brief covered:
- what a component claim observes: the interface, errors, permissions, storage in SPEC.md's names, caching,
  events and lifecycle;
- the assertion rule, constants cited by their class, and `dropped-throws.txt`;
- the licensing and phone-home rulings.

| group | modules | claims |
|---|---|---|
| m1-structures | structure-manager | 60 |
| m2-sync | sync-manager, sync-audit-log | 67 |
| m3-attributes-effects | attribute-service, attribute-subscription-service, effect-service, effector-process-manager, effector-instance-manager | 63 |
| m4-config-helper | structure-configuration, helper, structure-components | 58 |
| m5-history | history-service, statistics-manager, generic-item-history-manager, item-tracker, event-bridge | 79 |
| m6-forest-items | forest-service, structure-row-manager, generator-manager, item-resolver, item-type-registry, view-manager | 68 |
| m7-stores | generic-item-manager, generic-item-service, favorite-manager, folder-manager, memo-manager, planning-task-manager, structure-property-service, property-service | 73 |
| m8-platform | lifecycle, pinger, dependency-watcher, upgrade.001, cloud-data-migrator, app-support-store, backup-manager | 63 |
| m9-jobs-caches-query | job-manager, scheduled-job-manager, process-handle-manager, forest-permissions-cache, project-scope-cache, sub-task-issue-cache, structure-query-builder-factory, structure-query-parser | 78 |

- Confidence: 479 high, 130 medium.
- Length: the median claim is 383 characters.
- The fewest claims per module: `app-support-store` 2 (always licensed), `structure-components` 3, `upgrade.001` 3.
- No helper left an exported interface method unclaimed. Members that are not on the exported interfaces
  (for example `restoreItem` and `getMigrateOperation`) are not claimed.

**What I checked afterwards:**
- **Leak scan:** clean, with the stricter pattern.
- **Copying from the javadoc:** 8-word sequences against the vendor's javadoc (67,634 sequences). 2 claims
  match, both on the stock phrase "the structure does not exist or is not accessible".
- **Copying from the code:** a pattern scan for code-like text found nothing.
- **Quality:** I read a random sample. The claims are concrete and testable: exact keys, orders, error
  types, cache times, column names.

## Spec corrections (from the helpers' reports, checked where marked)

**SPEC.md (`contract-notes/`):**
- **New: the plugin's own error codes.** This is a table of 6001–6017: code, wire name, category. These codes
  reach clients in the structure-error body (`code`, `error`) and Java callers through `StructureException`.
  SPEC.md cited 6017 but never defined it; helpers needed 6005, 6008 and 6014 too. The wire name
  `USER_NOT_EXISTS_OR_INACCESIBLE` keeps the original's spelling. Checked against the class.
- **`AO_8BAD1B_GENERIC_ITEM.C_PARAMETERS`:** durations are stored in **milliseconds**, not seconds (examples
  changed to `7200000` and `28800000`). Checked: the parser reads Jira duration seconds and multiplies by
  1000; storage keeps the `Long`.
- **`AO_8BAD1B_SYNC_AUDIT_RECORD.C_DATA`:** added the `edit` action (`changedOwner`, `changedParameters`,
  `ownerKey`). For `installOffline` and `uninstall`, `parameters` is the stored text as a JSON string.
  Checked.
- **`AO_8BAD1B_FOREST_CHANGE`:** the trim job keeps the latest **501** changes, not 500.

**API.md (`api-notes/`), 27 member texts:**
- **Exceptions:**
  - `StructureConfiguration`'s four permission methods throw `IllegalArgumentException`, not
    `NullPointerException` (a dropped throw, checked);
  - `StructureJobManager.execute` (both forms) throws `StructureJobException` "illegal executor id …" (a
    dropped throw);
  - `BackupOperation.backupToStream(null)` throws `IllegalArgumentException` (a dropped throw);
  - `ItemTypeRegistry` throws `IllegalStateException` when the plugin is stopped;
  - `EffectorInstanceManager.getEffectorInstance` throws an unchecked exception on a storage failure;
  - `installSynchronizerOffline` throws on a blank module key;
  - `IssueListener`: an `Error` is not caught.
- **Error codes:** `EffectorProcessManager` (6017), `ForestService.getForestSource` (6008) and
  `StructureQueryParser.parse` (6005) now name their codes.
- **Behaviour:**
  - `HistoryService.getForestVersion` with a version below 0 is assertion-only (both outcomes);
  - `queryActivity` filters by row visibility only loosely, and its total is counted before filtering;
  - `ItemTracker.getUpdate(null)` returns a full update;
  - `ItemResolver.resolveItems` throws on duplicate identities;
  - `RowManager.findRows` with a predicate: a database error skips only the persistent rows;
  - `StructurePluginHelper.matchIssues` keeps ascending order only when reporting non-matches;
  - `setUISettings` stores four values;
  - `EffectService` expiry runs from when a batch was stored, so a batch stays loadable up to about 106 s;
  - `SyncAuditLog.getActions`: what the cap really does, and that a structure filter drops the actions;
  - `updateSynchronizer` checks only that the module is registered;
  - `ActionResult.getRowIdReplacements` returns an empty map from a stored structure.
- **Licensing:** `copyStructure` and `deleteStructure` say the original's read-only-licence failure never
  happens in the replacement (SPEC.md §1.1).

**`spec/README.md`:** Java assertions are enabled in tests, and claims state both outcomes (JC1 proposal 1).

## Tested

- New `tests/unit/test_jira_re_scan_throws.py`, 5 tests, written before the scanner:
  - constructed throws per top-level class;
  - rethrows and helper-built exceptions are not counted;
  - Java and Kotlin `throw` forms;
  - missing throws and missing sources;
  - compiler-made throws are ignored.
- **The private-helper case:** the scanner's first run on the plugin gave 12 false positives, all from
  private helpers called through `invokespecial`. That case was added to the test, then fixed.
- `test_jira_re_claims.py` has one new rejection case (an acronym-led name inside a dotted key);
  `test_jira_re_fixtures.py` has one new `check_spec` test (acronym-led names flagged; all-caps and plain
  words pass).
- `pytest`: 1,742 passed, 1 skipped (after the owner follow-ups below).
- jira-re `-m local`: 3 passed.
- `build_claims --check`, `build_api --check`, `build_contract --check`, `build_inventory --check` and
  `prepare_seed --check` are all up to date.
- Seed re-pinned: `ff6930be…` (after the owner follow-ups).

## Owner decisions after review (2026-10-28), applied in this phase

- **No licence checking at all.** SPEC.md §1.1 now says the replacement reads, validates and stores no licence
  data and never refuses, restricts or warns on licence grounds; any reported licence state is fixed. The
  licence modules keep their keys and types. Four claims were changed:
  - `structure-manager` and `view-manager` were reworded: they never fail on licence grounds;
  - `app-support-store` was reworded: it is never blocked and reads no stored data;
  - the `lifecycle` banner's licence summary was **retracted**.

  The brief now forbids describing licence logic. The API's licence value types keep their claims, because
  they are signatures.
- **The plugin's own error codes are contract**, as proposed.
- **Suspected bugs are flagged for checking during implementation.**
  - `build_claims` sets `"suspected_bug": true` on every claim whose text says "(as the original does)": 76
    claims, from JC1 and JC2. This is tested first.
  - `spec/README.md` explains the flag.
  - `stage2.md` (and `stage4.md` for API claims) tells the implementer to implement them as stated and to
    list each in `analysis/SUSPECTED-BUGS.md`: whether it agrees that it is a bug, the fixed behaviour, and
    what a fix would affect. It must not fix them itself.

  **Proposal:** a later hidden-side metric could measure the share of flagged claims listed there, per stage.

## Unresolved, and proposals

1. **Owner rulings needed:** none from this phase.
2. **Suspected bugs in the original,** stated as they are and marked "(as the original does)". They are
   candidates for `CHANGES-1.md`, and flagged `suspected_bug` for the implementer. The main ones:
   - **Permissions and visibility:**
     - `saveChanges` with nothing changed checks no permission;
     - `getView(id, null)` returns views the user has NONE access to;
     - a process whose managing user was deleted becomes visible to everyone;
     - `favorite-manager.clearUserCaches(user)` clears the current user's cache, not the given one's.
   - **Lost updates and half-done work:**
     - a failed forest copy leaves an empty new structure;
     - `setViewSettings` loses concurrent changes silently;
     - `enqueue` on a full queue still registers a job that never runs;
     - uninstalling a synchronizer does not cancel its queued resync;
     - the first apply run after a start interrupts every QUEUED effector process.
   - **Caches keep fallback answers:**
     - the forest-permissions, project-scope and sub-task caches keep the answer from a failed search;
     - a structure query reuses its last user context on the same forest;
     - sync listeners are decided once at start.
   - **Query parser:**
     - `(folder Foo)` is a syntax error;
     - validation finds constraint names by prefix, but execution needs the exact name;
     - the query builder's `toString` is not always parseable.
   - **Null and order paths:**
     - `queryActivity` with empty operations throws `NullPointerException`;
     - the synchronizer exclusion filters also drop manual entries;
     - `resyncOnce(null)` throws `NullPointerException`;
     - `isDefaultStructureSetForProject` is true for a project with no ID;
     - the deprecated `confirm(id, indexes)` applies duplicate indexes twice;
     - the sync audit cap has no ORDER BY.
3. **Not determined** (medium):
   - cluster-wide cache invalidation, for configuration, rows, views and generic items;
   - the Data Center sync-event and item-tracker timing;
   - restore internals beyond the operation level;
   - `HistoryEntry.getPrevVersion` for activity queries;
   - which custom fields generic items support.
4. **SPEC.md cloud migration** gives no chunk sizes (1 GiB Connect, 16 MiB Forge) and does not say that only
   the Forge path carries gadgets. The m8 claims state both. **Proposal:** leave SPEC.md as it is, since the
   sizes are tuning, not contract.
5. **Dropped `i++`:** m9 found that Vineflower also drops statements other than throws (an `i++` in a JQL
   query loop). The throw scan does not cover this. **Proposal:** briefs keep telling helpers to confirm odd
   paths with `javap`; no general statement diff.
6. **Still open from JC1:**
   - new hidden API behaviour tests written from the claims (then `selfcheck_api.py`,
     `gen_visible_api_tests.py`, `prepare_seed.py`);
   - the JS3 owner questions (`GenericItemHistoryManager` as contract, the API permission gaps for
     CHANGES-1, the licence type).

No spec decision (D-n) was changed.

## Next session

Module claims, continued: 563 modules. Suggested order:
1. the 166 remaining components, by group;
2. the many-instance extension types:
   - 63 `structure-attribute-loader-provider`;
   - 40 `structure-effect-provider`;
   - 34 `structure-item-type`;
   - 19 `structure-export-renderer-provider`;
   - generators;
3. the 84 web-resources (full UI behaviour), then the web items, sections and panels.

Use the helper brief `analyst/claims-brief.md` (JC2; adapt the module part per session), `dropped-throws.txt` and
`--validate`, then run `build_claims.py`, `check_spec.py` and `prepare_seed.py`.
