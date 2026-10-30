# Phase JC4: claims session 4, the extension modules (jira-re)

**Date:** 2026-10-29 · **Branch:** `jira-re` · **Design:** `docs/jira-re-design.md` §7.2, §7.4 · **Previous:** JC3

The third module-claims session. It wrote the claims for the 234 extension modules: the many-instance modules
that plug into the public API's extension points, and the `module-type` declarations of those points. No API
spend.

**Exit check (stated at the start):**
1. **Content.** All 234 extension modules have active claims covering each responsibility. That includes the
   module-type declarations, and the stored parameter, attribute and item-id formats stated exactly.
2. **Leaks and copying.** `--validate` passes for every notes file, `check_spec` finds no leaks, and nothing is
   copied from the vendor's javadoc.
3. **Spec errors.** Errors the helpers found are checked, fixed in the notes, and SPEC.md and the inventory are
   rebuilt.
4. **Green.** `pytest` and `-m local` pass, every `--check` mode is up to date, and the seed is re-pinned.

**Result: met.**

`check_spec`:
- 4,113 claims (1,267 new);
- modules with an active claim: 445 of 608;
- 164 problems: the 163 modules still to claim, plus the change-request placeholder.

## What was built

**Helper brief, JC4 version** (`analyst/claims-brief.md`). The module part now covers extension modules:
- **Contract.** The module key, type and descriptor element are contract. So are the stored and wire formats,
  which claims must state exactly:
  - generator parameters (the keys of `AO_8BAD1B_GENERATOR.C_PARAMETERS`);
  - synchronizer and effector parameters;
  - attribute ids and params keys;
  - item type keys and item id forms;
  - persisted i18n keys, given with their English text.
- **Not contract.** The implementing classes and their method shapes are not contract, and claims never name
  them.
- **What a claim covers.** For each kind of extension:
  - loaders: the specs answered and declined, values per item type, dependencies, aggregation, invalidation;
  - effect providers: parameters, problems, applying, undo, description;
  - item types: key, id form, resolution, visibility, tracking, create/copy/edit;
  - generators: stored parameters, form errors, rows produced, allowed and blocked actions, regeneration;
  - synchronizers and effectors: what they read and write, in which direction, conflicts, limits;
  - export renderers: cells per format;
  - module types: descriptor attributes and children read, defaults, ordering.
- **Integrations** are claimed both for when the other app is present and for when it is absent.
- Velocity templates and the HTML they render are left to the UI session.

`modules.txt` per helper now includes each module's descriptor element and the path of its decompiled source.

**The claims** were written by 14 helpers, each with its own scratch folder. A 15th deepened the weakest
areas:

| group | modules | claims |
|---|---|---|
| e1-module-types | 25 (19 module types, 4 new-structure templates, calendar provider, remote-gadget extension) | 87 |
| e2-loaders-a | 15 attribute loaders (main, icon, displayable, editable, sum, issue fields, …) | 75 |
| e3-loaders-b | 13 attribute loaders (custom fields, progress, work logged, generation info, …) | 73 |
| e4-loaders-c | 14 attribute loaders (formula attribute, comments, worklogs, links, epics, notes, …) | 66 |
| e5-loaders-d | 21 attribute loaders (aggregates, time in status, versions, generic items, Tempo, …) | 93 |
| e6-effects-a | 21 single-value effect providers | 97 |
| e7-effects-b | 19 multi-value and special effect providers, 4 effectors | 99 |
| e8-items-a | 17 item types (structure, issue, project, version, folder, generator, …) | 89 |
| e9-items-b | 17 item types (memo, planning task, effector, change history, Assets, …) | 95 |
| e10-inserters-extenders | 5 inserters, 4 extenders, the field grouper | 91 |
| e11-groupers-sorters | 7 groupers, 3 sorters | 84 |
| e12-filters-constraints | 9 filters, 5 S-JQL constraints | 78 |
| e13-synchronizers | 5 synchronizers | 93 |
| e14-export-perf | 19 export renderers, 10 performance-log providers | 105 |
| e15-deepen | sync-links and sync-gh placement, inserter-substructure placement and edits | 42 |

- **Confidence:** 1,050 high, 216 medium, 1 low.
- **Length:** the median claim is 376 characters.
- **Suspected bugs flagged:** 49 new, 165 in all.

**Modules with no behaviour of their own** (one claim each, saying what the module provides):
- the module types `structure-performance-log-provider`, `structure-query-skeleton-factory`,
  `structure-effect-provider`, `structure-backup-provider` and `structure-integration-details-provider`
  (the plugin declares no module of the last three types);
- `constraint-item`, the same constraint as `item-query-constraint`;
- five performance-log providers that only pass on an observer's log.

**Deepening (e15).** The synchronizer helper left the placement rules at low or medium confidence, as did the
inserters-and-extenders helper for the sub-structure inserter. I gave them to a fresh helper, which read the code fully
and wrote 42 claims with worked examples:
- sync-links: run order, orphan reuse and `orphanAction`, loop markers, cycles, duplicate merging;
- sync-gh: epics into and out of the structure, the rank algorithms, the step order of an incremental sync;
- inserter-substructure: placement after the inserter's subtree, edit pass-through and its permission checks.

It found that eight earlier JC4 claims were wrong or superseded (orphans, children order, orphan action,
epics in, ranks out, duplicates and loops, incremental order, and sub-structure rows). None had a permanent id
yet, so they were removed from the notes rather than retracted.

**dropped-throws.txt** changed three things:
- the synchronizer code lookups throw `IllegalArgumentException` for a missing `primacy` or `orphanAction`;
- the epic grouper and rank sorter throw "rank service is not found" from their form methods;
- the manual sorter throws when the subtree cannot be copied.

## Earlier claims and spec text corrected (checked in the code by me)

- **C-1759 (extension-service).** Query constraints are indexed by the descriptor's `fname` attribute, not by
  `name` (C-2154 had it right). Their order is an `<order>` child element, default `Integer.MAX_VALUE`.
- **C-1754 (extension-service).** Attribute loader providers and synchronizers read the `order` attribute
  (default 0). Query constraints read the `<order>` child element (default `Integer.MAX_VALUE`).
- **SPEC.md §1.5, `AO_8BAD1B_SYNC_INSTANCE.C_PARAMETERS` for sync-gh:**
  - in project mode `viewId` is written as JSON null, and an absent or null `viewId` reads as 0;
  - `syncRank` is always written;
  - `rankField` is written only in project mode, and only when a rank field is chosen.
- **Inventory, `number-sum-provider`:** a dependent requested in text format is declined, not summed as a
  number.
- **API.md, `BulkAccessCheckingItemType.filterInaccessible`:** the "collect every missing item" rule is the
  rule for other plugins' types. The built-in types follow their own claims, and several of them collect fewer
  items or none.
- **One JC4 claim's wording:** a `number-sum-provider` claim used "(as the original does)" for analyst
  commentary. The commentary is removed, so the claim is no longer flagged as a suspected bug.
- **Two helper findings checked and kept:**
  - Loaders return sub-tasks, parents and link counts without their own visibility check. This is correct,
    because the attribute service drops rows the user cannot see before any loader runs (C-1129), and
    sensitivity covers values computed over several items.
  - `filter-by-field` with an unknown field matches every visible issue. Confirmed and raised to high
    confidence.

## Tests

- `pytest`: 1,742 passed.
- `-m local`: 246 passed (exit code 0, under caffeinate), on seed `c51ac520`.
- `--check` is up to date for `build_claims` (4,113), `build_contract`, `build_inventory` and `build_api`.
- Seed re-pinned: `c51ac520`.

## Unresolved, and proposals

1. **Suspected bugs in the original** (flagged `suspected_bug`; candidates for `CHANGES-1.md`). The main ones:
   - **Effects:**
     - every custom-field effect provider swaps the arguments of its wrong-type message;
     - a non-numeric `value` for a select, cascade, version or project field silently clears the field;
     - an empty user parameter clears the field, but the description says `"null"`;
     - an unknown group in a multi-group effect shows a literal `{0}`;
     - a missing `memo` or an unsupported conversion `fromType` throws `NullPointerException`.
   - **Generators:**
     - the epic grouper's default `rankFieldId` text cannot be read back as a long;
     - moving into the Tempo "Excluded accounts" group clears the account;
     - the version grouper swaps message arguments and appends duplicate versions for memos;
     - a `filter-jql` form with no `jql` gives no error;
     - an unknown attribute-filter operator throws instead of giving a form error;
     - `filter-sjql` without a JQL part does not regenerate on item changes;
     - with breadth-first generation turned off, the sub-task extender keeps sub-tasks that are out of scope.
   - **Sync:**
     - with Jira Software ranks on a single project, the rank write checks `RESOLVE_ISSUES` (elsewhere it is
       `SCHEDULE_ISSUES`);
     - rank undo records success without checking;
     - the sync-gh resync decides a story's epic from its first row only;
     - a saved filter that is not found is still stored after the error;
     - the sync-links filter error text is missing a space.
   - **Loaders:**
     - for an anonymous user, a group-restricted comment or work log throws `NullPointerException`;
     - an uninstalled `calendar` makes time in status throw `NullPointerException`;
     - with no history, the transition-date list's initial entry is always the status id.
   - **Item types:**
     - the issue type's bulk check changes the caller's set;
     - placing a missing effector instance throws `NullPointerException`.
   - **Templates:**
     - the wizard loses earlier values when the user switches template;
     - a disabled template can still be used through a direct request.
   - **Remote gadget:** a subscription leaks when the window has no rows.
2. **Descriptor `name` values (owner OK, 2026-10-30).** Three item types' descriptor `name` attributes contain
   internal class names, so the validator rejects them and the claims leave them out. They stay out of the spec:
   t04 checks only module keys and types, and the descriptor names are not used at run time.
3. **Not determined** (medium):
   - Jira at run time: comparators (versions, status categories), duration and date formatters, and its own
     create, update and transition validation;
   - Assets and Tempo internals;
   - the order of graph traversals in independent ranking;
   - unstable sorts (sprint groups with equal state and sequence).
4. **Overlap between helpers.** The epic and rank change effects are claimed under both the groupers and
   sorters, where they are configured, and the extenders. They agree. Shared effect-provider behaviour is
   claimed in full on one module and referred to from the others.
5. **Still open from earlier phases:**
   - new hidden API behaviour tests written from the claims;
   - the JS3 owner questions;
   - the proposed hidden metric for `SUSPECTED-BUGS.md` coverage.

No spec decision (D-n) was changed.

## Next session (JC5)

The 36 remaining non-UI modules:
- the three REST modules (`rest-v1`, `rest-v2`, `rest-cfd`): per-endpoint behaviour beyond SPEC.md §1.3, such
  as permissions, errors and edge cases, by delegation to the claimed components;
- the 8 servlet filters, the `excel-export` servlet and the `ww-structure` webwork actions, including the
  rest of the create-structure wizard;
- the JQL function, the custom field type and searcher, the workflow condition and validator, the activity
  stream, and the three user handlers;
- the two simple-link factories, the transformer, the `ao` module and the 10 velocity allowlists.

After that, the 127 UI modules: 84 web-resources (full UI behaviour), 24 web items, 12 web sections, 4 web
panels, 2 gadgets and the keyboard shortcut. These need a brief module part for UI behaviour.
