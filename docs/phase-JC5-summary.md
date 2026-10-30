# Phase JC5: claims session 5, the non-UI surface modules (jira-re)

**Date:** 2026-10-30 · **Branch:** `jira-re` · **Design:** `docs/jira-re-design.md` §7.2, §7.4 · **Previous:** JC4

The fourth module-claims session. It wrote the claims for the 36 remaining non-UI modules: the REST modules,
the webwork pages, the servlet filters and servlet, the Jira hooks, `ao` and the Velocity allowlists. No API
spend.

**Exit check (stated at the start):**
1. **Content.** All 36 modules have active claims. Every one of the 163 REST endpoints and all webwork aliases
   and commands is covered by name, checked by script.
2. **Leaks and copying.** `--validate` passes for every notes file, `check_spec` finds no leaks, and nothing is
   copied from the vendor's javadoc.
3. **Spec errors.** Errors the helpers found are checked, fixed in the notes, and SPEC.md and the inventory are
   rebuilt.
4. **Green.** `pytest` and `-m local` pass, every `--check` mode is up to date, and the seed is re-pinned.

**Result: met.** Items 1 to 4 pass, with the limit on item 3 stated under "Earlier claims and spec text
corrected": I rechecked the main findings in the code, and applied the rest on the helpers' reading.

`check_spec`:
- 5,368 claims (1,255 new);
- modules with an active claim: 481 of 608;
- 128 problems: the 127 UI modules still to claim, plus the change-request placeholder.

## What was built

**Helper brief, JC5 version** (`analyst/claims-brief.md`). The module part now covers:
- **REST endpoints.** Claims add what SPEC.md §1.3 does not say: permission per action, check order, clamps,
  edge cases. Each helper also read the SPEC.md entry of every endpoint against the code.
- **Webwork pages.** Per alias and command: parameters, who may open it, what it does on GET and submit,
  redirects, errors, and the facts a page presents, never its HTML.
- **Filters and the servlet.** Which requests they act on and what they do to them.
- **Jira hooks.** Whatever Jira stores or calls is contract.
- **Velocity allowlists.** Only the key and type are contract. The listed methods are the original's, and the
  implementer lists its own getters.

Each helper also got a `scope.txt` listing its sources and the endpoints or aliases it owned, so several helpers
could share `rest-v1`, `rest-v2` and `ww-structure`. Endpoints came from `hidden/_contract.py`, which found
four Kotlin resources a source scan had missed.

**The claims** were written by 12 helpers, each with its own scratch folder. A 13th deepened the weakest areas:

| group | scope | claims | suspected bugs |
|---|---|---|---|
| r1-v1-config | `rest-v1`: config, fields, UI, widget (20 endpoints), shared conventions | 88 | 3 |
| r2-v1-gadget-view | `rest-v1`: gadget, perspective, S-JQL troubleshooting, statistics, view (24) | 78 | 6 |
| r3-v2-forest | `rest-v2`: forest, poll, generation, mapping, subscriptions, sensitivity, process (20) | 79 | 4 |
| r4-v2-items | `rest-v2`: item, value, effect, effector process, expression, macro, query, note, generic item (28) | 124 | 8 |
| r5-v2-structures | `rest-v2`: structure, manage, welcome, history, saved column, undo, create, cloud migration (35) | 97 | 4 |
| r6-v2-config-cfd | `rest-v2`: configuration, pickers, Tempo and others; `rest-cfd` (36) | 64 | 2 |
| f1-filters-excel | the 8 servlet filters, `excel-export` | 95 | 8 |
| w1-pages-structures | `ww-structure`: 20 aliases (board, wizard, copy, views, help) | 185 | 6 |
| w2-pages-admin | `ww-structure`: 18 aliases (admin, backup, restore, migrate, maintenance) | 127 | 7 |
| w3-pages-sync-effectors | `ww-structure`: 12 aliases (sync, processes, effectors, generator edit) | 152 | 8 |
| i1-jira-hooks | JQL function, activity stream, workflow, custom field, handlers, link factories, transformer | 112 | 5 |
| i2-ao-allowlists | `ao`, the 10 Velocity allowlists | 24 | 0 |
| d1-deepen | migrate field resolution; `forest/update` with an empty fragment | 30 | 6 |

- **Confidence:** 1,119 high, 133 medium, 3 low.
- **Length:** the median claim is 375 characters.
- **Suspected bugs flagged:** 67 new, 231 in all.

**Modules with no behaviour of their own:**
- `end-of-life-decorator` and `plugin-manager-helper` pass requests through and never add their resource (no
  licensing);
- the three user handlers only gather what other modules contribute;
- `widget-i18n-transformer` delegates to modules claimed earlier;
- `ao` declares the schema.

**Coverage, by my own script over the notes** (the helpers' reports were not taken for it):
- 163 of 163 endpoints appear by method and path;
- all 50 aliases and all their non-trivial commands appear, matched on word boundaries. `!apply` and `!default`
  are covered by shared claims stating that every page has them.

**Tooling changes** (test-first):
- **`build_inventory.py`.** `contract.actions` listed only commands declared by `<command>`. Webwork runs `!x`
  through any public `doX()`, so 106 commands were missing: `!apply` and `!default` on every page, which is where
  most forms submit, and the effector pages' `applyEffects`, `dismiss`, `acknowledge`, `resume` and `undoEffects`.
  They are now read from the action classes, 126 commands in all, and SPEC.md §1.4 says so.
- **`scan_throws.py`.** It only counted `new T; athrow`, so it missed exceptions built by a method call, such as
  `throw StructureErrors.X.withMessage(...)`. It now counts those as `name()`, and leaves out `access$n`
  accessors and Kotlin intrinsics. Two older tests pinned the old limitation and were updated on purpose.
  `dropped-throws.txt` is regenerated.

## An error in earlier phases, found by the scanner fix

The extended scan listed three new classes. One changed the spec:

- **C-1186 (`effector-instance-manager`) was wrong**, and so was `API.md`. They said `getEffectorInstance` returns
  null for a missing id, "although declared not-null". Vineflower dropped the throw: the bytecode throws
  `ITEM_NOT_EXISTS_OR_NOT_ACCESSIBLE`, and every caller catches `StructureException`.
- **The same holds for `GeneratorManager.getGenerator`** (C-1357 and `API.md`). The internal managers do return
  null; the facade that callers use throws.

What followed:
- C-1186, the delete claim beside it, C-1357 and both `API.md` rows are corrected;
- **C-4043** (`type-effector`) described a `NullPointerException` that does not happen. It no longer carries the
  suspected-bug flag, and that bug in the JC4 summary's list is withdrawn;
- two of w3's new suspected bugs were built on C-1186 and were false. Those claims now state the real outcomes:
  an error result on `StructureEffectorEdit`, and `Effector instance #{0} is not found.` on
  `StructureEffectorProcess`.

**Lesson for the next sessions:** a claim that a method "returns null although declared not-null" is a warning
sign. The brief now says so.

## Earlier claims and spec text corrected

**Checked in the code by me:**
- **The wire form of `error`.** §1.3 said the name is the exact wire string. It is `<NAME>[<code>]`, for example
  `INVALID_JQL[6003]`, for public and plugin codes. This reaches every REST error.
- **`rowId`** in the error object is always present, 0 when no row is concerned.
- **The administrator-only list in §1.3** missed `/attribute-sensitivity`, `/configuration`, `/dark-features` and
  the system-administrator `/cloudmigration`.
- **`GET /history/{id}/versions`:** `maxVersion` is exclusive, and `maxCount` caps the list even with `withVersion`.
- **Saved columns:** `name` is mandatory and trimmed, blank or over 190 characters gives 400 (also C-1723).
- **`GET /tempo/accounts`:** archived accounts are left out unless `structure.tempo.showArchivedAccounts` is true.
  SPEC.md had it backwards.
- **`GET /forest/latest`:** a missing or unparsable `s` gives `Invalid request data` / `Forest spec is required`.
- **`forest-update-response.undoEffects`** is emptied at the start of each action; it is not the last successful
  action's effects.
- **`excel-export`:** a missing or forbidden `viewId` silently gives the default view and does not try `viewSpec`,
  so there is no 404 for views. Failures go through `sendError`. A w1 claim on the printable view said the
  opposite and was fixed, since both share the code.
- **Group picker:** the 403 for anonymous callers cannot be reached, because the platform answers 401 first. The
  same goes for `create-structure/*`.
- **`GET /date/validate`:** only `IllegalArgumentException` gives `isValid` false.
- **Migrate:** perspectives are not migrated, so the old-to-new mapping in §1.6 is always empty.

**Applied on the helpers' reading of the code, not rechecked line by line by me:**
- `{}` replaced by `{"empty": true}` for `empty-ok` replies throughout, and C-2522;
- `GET /perspective/{id}` is double-encoded;
- the view endpoints: name search is a substring, `forPage` omitted behaves like `structure`, `spec` is required,
  and update failures are always 404;
- the S-JQL troubleshooting arguments, the gadget pickers' 9-match rule, and the statistics record collisions;
- `config/ui` errors, `forCreate` rendering, the `config/projects` permission lookup, and application-then-system
  property wording;
- `quick-transforms` entries without `key` give 500;
- effect undo and redo on a plain forest, paging order, `cancelAndWait` and the `genericItem` number range;
- `excel-export`: filename leading run, `xlsx` matching, time zone;
- `runAsLead`, `structureType` and the workflow and user-key inventory purposes;
- process visibility for ownerless processes;
- backup format item 5, and the `ErrorsContainer` note in API.md.

I spot-checked one doubtful finding: r3's `Forest spec is required` looked wrong until the search included the
API jar. It was right. No helper finding I checked turned out false, apart from the two that rested on C-1186.

**Left in the claims only, not in SPEC.md:** the many 500s from a null body or missing nested field, which SPEC.md
does not contradict.

## Tests

- `pytest`: 1,744 passed, 1 skipped (exit code 0), rerun after the owner rulings. The two new tests are in
  `test_jira_re_scan_throws.py`.
- `-m local`: 247 passed (exit code 0, about 1:38 under caffeinate), on seed `1d6342ff`. It was not rerun after the
  rulings, which changed spec text only (as in JC3). The new test is the inventory's webwork commands, which needs
  a JDK.
- `--check` is up to date for `build_claims` (5,368), `build_contract`, `build_inventory` and `build_api`, and
  `prepare_seed.py --check` agrees with the pinned seed after both runs.
- Seed re-pinned: `1d6342ff`, then `a65bc321` after the owner rulings (spec text only).

## Unresolved, and proposals

1. **Owner rulings (2026-10-30), both accepted as proposed:**
   - **Fixed licence values.** SPEC.md §1.1 now gives them exactly: `license-info` type `commercial`, empty licensee
     and serial, unlimited users, `maxUsers` 0, source `none`, no server lock, no expiry; `licenseSEN` null and
     `unlicensed` false; `LicenseData` the same. The four claims and the API.md note are updated, and the three
     REST claims are now high confidence.
   - **`welcome/gantt-link`.** The link depends only on Gantt being enabled and the create right, with no licence
     question to Gantt.
2. **The confidence counts above** are as of the helpers' work; the three claims in item 1 moved from medium to high.
3. **Suspected bugs in the original** (flagged `suspected_bug`; candidates for `CHANGES-1.md`). The main ones:
   - **Forest update:**
     - an action's content is checked only when the run reaches it, so a bad action n gives 400 while actions
       1..n-1 stay applied;
     - parsed `cutFrom.spec` values are consumed only by `add`, so an earlier `copy`, `move` or `remove` makes a
       later add remove rows from the wrong forest;
     - an empty `add` with a stale signature gives 500 `Index 0 out of bounds for length 0`, and an empty `add`
       on a structure can never succeed.
   - **Applied, then failed:** `item/create`, `item/update` and effect undo give 500 after the change is made when
     `items.version` is absent. `POST /config/ui` stores preferences, then answers 404.
   - **Permissions and safety:**
     - `StructureSync` create checks no app permission or archived state;
     - `StructureProcessStatus` cancels on a GET with no XSRF check;
     - in the workflow condition, the query runs as the caller, not the run-as user;
     - a read oddity, not flagged: any Structure user can read an effector's stored parameters by id.
   - **Data loss:**
     - `EditStructure`: permissions text that is not valid JSON saves as no rules;
     - a copy cancelled at the warnings stop leaves its clones in Jira;
     - perspectives are never migrated.
   - **Migrate problem reports:** field problems can appear under the wrong structure, and one problem set can
     overwrite another.
   - **Filters:** `security-filter` swallows every `Exception` from the chain, and a failure computing its policy
     leaves an empty response.
   - **Allowlists (reported, not claimed):** one malformed entry in `create-structure-allowlist`, and three methods
     templates call but no allowlist lists. The replacement lists its own.
4. **Not determined** (medium):
   - what Jira 9.12 shows for a webwork outcome with no mapped view, which several pages reach;
   - what Jersey does with a wrongly typed query or path parameter, and whether body parsing precedes the gate;
   - how Jira's user search and date parser treat null;
   - the order of link origins in `frame-ancestors` (a hash set), and of the user handlers' contributors.
5. **Overlap between helpers.** `ForestExporter` behaviour is claimed under both `excel-export` and the printable
   page, and they now agree. The shared webwork rules are claimed by each of the three page helpers, in their own
   words.
6. **Still open from earlier phases:**
   - new hidden API behaviour tests written from the claims;
   - the other JS3 owner questions;
   - the proposed hidden metric for `SUSPECTED-BUGS.md` coverage.

No spec decision (D-n) was changed.

## Next session (JC6)

The 127 UI modules: 84 web-resources (full UI behaviour), 24 web items, 12 web sections, 4 web panels, 2 gadgets and
the keyboard shortcut. These need a brief module part for UI behaviour, and a source other than Vineflower, because
the logic is in JavaScript and Velocity templates. The page claims here give the data each page shows, so the UI
session can build on them. The Velocity allowlists' `values-read` claims list the kinds of values templates read.

After that: `spec-changes-1.md`, the last `prepare_seed.py`, and the full run.
