# Phase JC3: claims session 3, the internal components (jira-re)

**Date:** 2026-10-29 · **Branch:** `jira-re` · **Design:** `docs/jira-re-design.md` §7.2, §7.4 · **Previous:** JC2

The second module-claims session. It wrote the claims for the 166 internal components: the Spring components
the plugin does not export. With JC2's 45 public components, every one of the 211 components now has claims.
No API spend.

**Exit check (stated at the start):**
1. **Content.** All 166 remaining components have active claims, covering each responsibility.
2. **Leaks and copying.** `--validate` passes for every notes file, `check_spec` finds no leaks, and nothing is
   copied from the vendor's javadoc.
3. **Spec errors.** Errors the helpers found are checked, fixed in the notes, and SPEC.md and the inventory are
   rebuilt.
4. **Green.** `pytest` and `-m local` pass, all `--check` modes are up to date, and the seed is re-pinned.

**Result: met.**

`check_spec`:
- 2,846 claims (1,238 new);
- modules with an active claim: 211 of 608;
- 398 problems: the 397 modules still to claim (none of them components), plus the change-request
  placeholder.

## What was built

**Helper brief, adapted** (`analyst/claims-brief.md`, JC3 version). Internal components have no contract
interface, so the module part now says:
- a claim states **what the component does for the plugin**: its rules, limits with their numbers, storage in
  SPEC.md's names, what it asks Jira, caching and timing, and what shows through REST or the public API;
- it never names the component's methods or internal types, because the implementer designs its own;
- big catalogues get one claim per entry or small family (the formula function library, the bundled columns,
  the statistics counters);
- thin bridges get a short claim of what they report on Jira 9.12 and how they fail;
- only the Jira 9.12 variant of a module is claimed (SPEC.md: the pinned platform);
- licence and vendor modules get only the fixed answers from SPEC §1.1 and §1.8 and INVENTORY §5. Their helper
  was told not to read the original's licence, certificate, serial or Marketplace logic.

**The claims** were written by ten helper agents, each with its own scratch folder.

| group | modules | claims |
|---|---|---|
| c1-platform | 21 (Jira-version bridges, cluster caches and locks, formatting, i18n bundles, server-side state) | 75 |
| c2-persistence | 15 (storage of rows, generators, processes, history, notes, columns, statistics; database lock and access) | 124 |
| c3-expr-attributes | 13 (formula language parser, ~150 functions, aggregations, limits; attribute-subsystem helpers) | 171 |
| c4-query-perms-sync | 17 (index search, S-JQL constraints, query caches, the permission calculator and caches, sync event queue) | 145 |
| c5-integrations | 17 (Jira Software, Advanced Roadmaps, Tempo, Assets, Service Management, ScriptRunner, others; bulk links, mail) | 121 |
| c6-events-userdata | 15 (event bridges, history recorder, reindex tracking, statistics sources, anonymisation, recents, issue cloner) | 131 |
| c7-perf-cfd-support | 20 (performance observers and logs, the CFD back end, five licence/vendor modules) | 102 |
| c8-model-generators | 17 (item identities, transient rows and generators, clipboard, field types and catalogue, generic-item fields, adjustments) | 133 |
| c9-ui-rest-admin | 20 (services behind UI pages, pickers and REST, perspectives, maintenance, help, cloud-migration configuration) | 143 |
| c10-columns-ext | 11 (the view store, icon caches, saved-column sources incl. the 17 bundled columns, note search, extension registry) | 93 |

- Confidence: 1,093 high, 143 medium, 2 low.
- Length: the median claim is 382 characters.
- Suspected bugs flagged: 38 new, 116 in all.
- Modules with no behaviour of their own (one claim stating what they provide):
  - `jira-components`;
  - `expr-function-services`;
  - six thin forwarders: the attachment, web-resource URL, web-resource manager, servlet variables, action
    context and XML date bridges;
  - the three vendor modules `app-support-connector`, `app-support-client` and `certificate-manager`, which
    keep their keys and do nothing.
- **Dropped throws** (`dropped-throws.txt`) changed two claims:
  - the database provider has a third fatal error, when the bootstrap row has no entity manager;
  - the link-generator effect blocks a change whose link type is missing or hidden (`s.gen.links.block.no-link-type`).

  Helpers also used `javap` on the Kotlin classes Vineflower could not decompile, which found two of the
  suspected bugs below.

**Earlier claims corrected** (checked in the code by me, not only by the helper; ids unchanged):
- **C-1022 (structure-manager, permission rules).** It said that only references closing a cycle are skipped.
  In fact, below the structure's own top level, every structure that has applied another one is remembered for
  the rest of that reference, so a later repeat in a sibling branch is skipped too. It is now flagged as a
  suspected bug, with the helper's example: S1 gives NONE, S2 on its own gives VIEW.
- **C-1081 (sync-manager, autosync).** On Data Center, the "autosync enabled" marker reads the latest history
  version of the structure whose id equals the *synchronizer instance id*. It is now flagged as a suspected bug.
- **C-1448 (planning-task-manager).** Multi-valued fields drop only their invalid elements; they don't read as
  null.
- A c8 claim had spelled out a dark-feature key that contains an internal class name in pieces, to get it past
  the validator. It now says "a tuning setting; its key is not contract", following the JC2 rule.

**SPEC.md fixes** (in `contract-notes/`, rebuilt):
- **Licence leftovers removed.** Eight saved-column REST entries said "not available in license read-only
  mode", against §1.1 and §1.8.
- **§1.5 tables:**
  - `AO_8BAD1B_HISTORY_CHANGE` and `AO_8BAD1B_MANUAL_ADJUSTMENTS` hold *public* row ids (ID × 2, as in
    `AO_8BAD1B_FOREST`), not `AO_8BAD1B_ROW.ID`. Checked in the history writer and the adjustment code.
  - `AO_8BAD1B_BOOTSTRAP` may be created with `C_IS_LOCKED` NULL; both NULL and false mean unlocked.
  - `AO_8BAD1B_SYNC_EVENT`:
    - an unknown type code fails an assertion, so with assertions on it throws `AssertionError`;
    - the type-126 payload has the instance-id bug above.
  - `AO_8BAD1B_PERSPECTIVE.C_SPEC`: the example now has `primary.forestSpec.structureId`, which is what the
    mail sender reads. Checked.
  - `AO_8BAD1B_MIGRATION_CONFIG.C_STRUCTURE_IDS`: an empty string cannot be read back, so it no longer means
    "none".
  - Index-monitor custom field: only the first field of the type is checked, and an existing field is not
    locked again.
- **§1.6 names:**
  - added the SAL user setting `almworks.jira.structure.recents`;
  - removed the `AOLock` cluster locker. No such locker exists: `AOLock…` is only a cache name, and ao-lock
    uses a JVM lock. The lockers in use are `sjm`, `ViewManagerInit` and `ievent-signature-lock`.
- **REST:**
  - the `create-structure/*` pickers do a literal substring match, shortest name first;
  - option-picker sprint suggestions are always empty, and versions and components sort by name only;
  - `/issue-field` leaves out global-context custom fields;
  - `formula-name-usage.name` is lower-cased, and names that differ only in case are merged;
  - CFD:
    - `deviation` is a median absolute deviation of the runs' total durations;
    - meta and validate reject an absent `trainingPeriod`;
    - the simulation needs all four attribute specs;
    - with the feature off, the caller gets the generic error.
- **Inventory purposes:**
  - `jira-thread-env-factory`: request emulation is off unless the dark feature is set;
  - `transient-row-manager`: rows live until restart.

## Tests

- `pytest`: 1,742 passed.
- `-m local`: 246 passed (1:46:41, under caffeinate), on seed `c330a641`; not rerun after the rulings, which changed SPEC.md text only (`pytest` and every `--check` were rerun: green).
- `--check` is up to date for `build_claims` (2,846), `build_contract`, `build_inventory` and `build_api`.
- Seed re-pinned: `c330a641`, then `1637a00b` after the owner rulings (SPEC.md text only).

## Unresolved, and proposals

1. **Owner rulings (2026-10-29), both accepted as proposed:**
   - **Bundled formula columns.** The 17 bundled columns are claimed by what their formula computes, in my own
     words; the original formula strings (which contain the vendor's comment prose) are not copied. Hidden tests
     check these columns by the values they compute, never by the formula text.
   - **Vendor-job keys.** `appSupport.lastCheckTime` and `licenseCheck:<module key>` are out of the contract.
     SPEC §1.6 now lists only the three remaining job keys and says the replacement runs neither vendor job nor
     writes their `sjm.*` rows; the `app-support-client` inventory note says the same. SPEC.md and the inventory
     are rebuilt, and the seed is re-pinned (see Tests).
2. **Suspected bugs in the original** (flagged `suspected_bug`; candidates for `CHANGES-1.md`). The main ones:
   - **Permissions:**
     - nested apply-rule repeats are skipped (C-1022);
     - a user rule with a null user key matches the anonymous user;
     - anonymisation lists archived private structures but never handles them.
   - **Sync and indexing:**
     - the autosync marker uses the instance id as a structure id;
     - a Data Center drain that fails part-way deletes the rows it already read;
     - an interrupted wait for the index lock throws `IllegalMonitorStateException`;
     - the sorted index search ignores the user it is given.
   - **Integrations:**
     - Service Management request types always cost 1,001 page requests;
     - an unresolvable Assets status throws `NullPointerException`.
   - **Formula language:**
     - `substring` past the end gives error 6;
     - element-wise functions silently drop error elements (`sqrt(array(4,-1))` is `[2]`);
     - `.name` access lower-cases the key.
   - **Statistics and CFD:**
     - double counts in the feature statistics;
     - the statistics report throws for mixed user and no-user rows;
     - an epic whose only children are epics still counts;
     - the `Other` team chart is always empty;
     - the two issue-type error messages are swapped.
   - **Small:**
     - recents store max+1 ids;
     - bulk archiving records no change;
     - a picker group-key mismatch;
     - a migration configuration with an empty string cannot be read;
     - `maintenance.successful` keeps a partial outcome;
     - a whitespace-only note search matches nothing.
3. **Not determined** (medium): what Jira itself does at run time, such as:
   - the null current request, `TextUtils` escaping and JAXB date output;
   - the display-name search case, anonymous group and role membership, and Lucene's clause limit;
   - the Tempo JQL text, ScriptRunner internals and the OfBiz batch size;
   - duration formatting, Velocity escaping and `CronExpression`/DST edge cases.
4. **Descriptor oddity:** the Jira 11 `servlet-bridges` entry has `version="[11.0.0)"`. It is out of scope
   (Jira 9.12 only), so this is a note only.
5. **Still open from earlier phases:**
   - new hidden API behaviour tests written from the claims;
   - the JS3 owner questions;
   - the proposed hidden metric for `SUSPECTED-BUGS.md` coverage.

No spec decision (D-n) was changed.

## Next session

Module claims, continued: 397 modules, none of them components. Suggested order:
1. the many-instance extension types:
   - 63 `structure-attribute-loader-provider`;
   - 40 `structure-effect-provider`;
   - 34 `structure-item-type`;
   - 19 `structure-export-renderer-provider`;
   - 19 `module-type`;
   - the generators (inserters, extenders, groupers, sorters, filters), synchronizers, effectors and query
     constraints;
2. the servlet filters, REST modules, JQL function, custom field, workflow and user-data handlers;
3. the 84 web-resources (full UI behaviour), then the web items, sections and panels.

The brief needs a new module part for extension modules: what a loader, effect or item type does through the
API's extension interfaces. Then use `dropped-throws.txt` and `--validate`, and finally run `build_claims.py`,
`check_spec.py` and `prepare_seed.py`.
