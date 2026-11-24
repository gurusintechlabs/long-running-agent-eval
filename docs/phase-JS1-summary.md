# Phase JS1: analyst spec session 1, the inventory (jira-re)

**Date:** 2026-10-28 · **Branch:** `jira-re` · **Design:** `docs/jira-re-design.md` §7.2 · **Previous:** JA1

The first analyst session (Claude, in a development session, outside any LRAE run). It produced the inventory,
which the rest of the spec hangs off. It used no API spend.

**Exit check (stated at the start):**
- `check_spec.py` reports no `inventory.json` problems: all 608 modules are present, each with the original
  type and a purpose.
- No internal names leak into `spec/`.
- `INVENTORY.md` is written.
- `pytest` is green.

**Result: met.** `check_spec.py` reports 608 inventoried and 1,079 problems, down from 1,080 (see below).
None of the remaining problems is an inventory problem or a leak. They are claims (608), SPEC.md API types
(417), API-test mapping (51), and the missing `claims.jsonl`, `claims-evidence.jsonl` and change-request
placeholder.

The count fell by one only because the inventory is the smallest part of the check. Writing a correct inventory
cleared the one "inventory.json is missing" problem.

## What was built

**Seed `spec/` (read by the implementer):**
- `inventory.json`: all 608 modules, each with:
  - `key`, `type`;
  - `name`, the display name, kept only where it is not an internal label (component names are dropped);
  - `class`, the contract class where the contract fixes one: today only the workflow condition and validator;
  - `group`, one of 25 subsystems, with a legend;
  - `purpose`, `related` and `confidence`;
  - `contract`: the externally visible parts of the declaration that applies to Jira 9.12. These are
    REST paths, URL patterns, locations and sections, labels, web-resource contexts and dependencies,
    exported interfaces, webwork aliases and commands, and JQL fname. The `ao` module also carries the
    39 table names and the `AO_8BAD1B_` prefix (checked: the last six hex digits of the MD5 of the
    namespace, the Active Objects rule).
- `INVENTORY.md`, in five sections:
  - what the plugin is;
  - modules by type;
  - how the subsystems fit together;
  - the contract the inventory already fixes;
  - a module index by group, generated between markers.

**Analyst side (`fixtures/tasks/jira_re/analyst/`, never in the seed):**
- `build_inventory.py` writes `spec/inventory.json` and the INVENTORY.md index from the jar's descriptor and
  `inventory-notes.json`. `--check` reports staleness. It drops any descriptor value or display name that
  names an internal class, dotted or by its simple name.
- `inventory-notes.json` holds the analyst's notes per module: purpose, group, related, confidence, extra
  contract facts, and `contract_notes`. The contract notes may name classes, so they stay harness-side.
- `contract-classes.txt` lists the names `spec/` may use although they are classes of the jar:
  - `StructureWorkflowChecker`, which Jira stores in workflow XML;
  - `GenericItemHistoryManager`, an exported OSGi interface outside the public API;
  - the 50 webwork aliases. Each alias is also an internal class's simple name, but it is a contract
    URL (`/secure/<alias>.jspa`).

**`check_spec.py`, two stricter leak rules:**
- **Simple names.** A CamelCase simple name (two humps or more) of an internal class now counts as a leak.
  Before, only dotted names were caught. A bare word in `contract-classes.txt` allows it.
- **Bundled internal libraries.** These ship in the jar's `META-INF/lib`: `structure-commons`, `compat-jira*`
  and `structure-shared-*`. They are named by a new `internal_libs` key in `target.yaml`, and their class
  names count as leaks too. The rule is configured, not guessed: a "vendor package" heuristic wrongly
  flagged the public `com.almworks.integers` library, which is part of the API's contract.

**Seed re-pinned:** `e31369d2…`, since `spec/` changed (after the follow-up below).

**Decompiled for later sessions:** `analyst-work/libvf/` holds the four internal libraries (git-ignored,
Vineflower).

## How it was done

The descriptor was split into six clusters: components in three parts, the web layer, attribute/effect/export
extensions, and the other extension and singleton modules. One helper agent per cluster read the decompiled
code and wrote purposes under clean-room rules: no class, method or field names, and no copied code or
comments.

I then:
- merged their output and checked coverage, groups and related keys;
- spot-checked purposes;
- verified the AO prefix;
- found and fixed four entries that rested on missing code: `number-sum-provider`,
  `non-unique-items-provider` and `primitives-provider` were wrongly reported as absent from the jar, and
  `ao-lock` was low confidence. Their classes are in `structure-commons`, which I decompiled and read;
- removed one statement I could not verify (that row ids separate stored rows from generated ones);
- corrected counts in INVENTORY.md against the descriptor.

## Tested

- New unit tests in `tests/unit/test_jira_re_fixtures.py`:
  - simple-name leaks;
  - leaks from bundled internal libraries, and no false hit on a third-party library;
  - the inventory builder: `<restrict>` selection for the pinned Jira, internal names dropped, contract
    class, exports, webwork aliases, labels;
  - the INVENTORY.md index splice.
- `pytest`: green.
- `-m local` for the jira-re files (3 tests): green.
- The full `-m local` run is left for the end of the track, as planned.
- `build_inventory.py --check`: up to date.

## Unresolved, and proposals

1. **Grounding cannot see the bundled internal libraries.** `hidden/_support.reference()` reads only the
   jar's top-level classes. Real behaviour lives in `structure-commons`: the `sum` and `count` attributes,
   the database lock, the licence manager, base classes of many components. So a claim whose evidence is
   there fails "not in the jar".
   - **Decided (owner, 2026-10-28): yes.** Done in the follow-up below.
2. **The plugin phones home.**
   - The app-support client posts licence facts daily to the vendor's server. Its HTTPS client trusts any
     certificate.
   - Usage statistics are sent daily, but only after an admin opts in.
   - It checks the Marketplace for updates.

   **Decided (owner, 2026-10-28): out of scope; the replacement never contacts the vendor.** Done in the
   follow-up below.
3. **One exported non-API interface,** `GenericItemHistoryManager`. Other plugins look it up as an OSGi
   service, so SPEC.md must give its signatures as contract, like the public API.
4. **The public API names an undeclared effect provider key,** `resolution-date-effect-provider`. To check
   in the effects claims session.
5. **Confidence:** 509 high, 99 medium, no low. Most medium entries are components whose logic is in
   `structure-commons` (decompiled only at the end of this session) and web-resources with thin code.
   Each is raised when its claims are written.
6. **Jira 11 declarations** (jakarta servlets, separate REST classes) are outside the pinned 9.12 build. The
   inventory records only the declaration that applies to 9.12 and flags the key
   (`declared_per_jira_range`).
7. **Front-end hooks** that no module declares: the contexts `structure.widget` and `structure.printable`,
   and the web-item location `structure.export.menu`. They are extension points for companion apps, so the
   SPEC contract section will list them.

No spec decision (D-n) was changed.

## Follow-up: the owner's two decisions (same day)

1. **Evidence and the copy-similarity reference cover the internal libraries.**
   - `hidden/_support.reference(jar, libs)` adds the classes of the bundled jars that match `libs`
     (globs). `check_spec.py` passes `internal_libs`, so evidence such as a class in `structure-commons`
     now resolves (3,603 classes before, 4,231 with the libraries). Its separate bundled-class helper is
     gone; the leak rules read the same reference. The hidden tests themselves are unchanged (they use
     only the modules).
   - `jira_target.load` resolves `internal_libs` like `public_api` (a glob matching nothing is an error);
     `prepare_seed.py` extracts them to `vendor/lib/` (git-ignored) and reports staleness.
   - `scoring.clean_room.extra_jars` now also takes a list of jars or dirs (schema, loader resolution and
     per-path content hash, scorer, UI field as JSON). `spec/examples/jira-re.yaml` lists `vendor/api`
     and `vendor/lib`. A single string is hashed as before, so other specs keep their hash. This is a
     schema extension, not a D-n change.
   - Not exercised against the real jars yet: the Vineflower decompile of `vendor/lib/` first happens at
     the first scored checkpoint. Unit-tested with a stub decompiler.
2. **Phone-home is out of scope.** INVENTORY.md has a new section 5, "Out of scope: contacting the
   vendor" (the module index is now section 6), and the purposes of `app-support-client`,
   `app-support-connector`, `plugin-update-checker` and `statistics-manager` say what stays. Module keys
   stay (they are contract); no network sending; with no reports no serial is ever blocked; the update
   check always reports none; statistics are collected, stored and purged locally and the opt-in is
   recorded, but nothing is uploaded. SPEC.md must repeat this in its contract section.

Tests added: list-valued `extra_jars` (schema and scorer), `internal_libs` extraction, evidence grounding
in a bundled library, and the out-of-scope wording in `spec/`. `pytest`: 1,682 passed; jira-re `-m local`:
green; `prepare_seed --check` and `build_inventory --check`: up to date; `check_spec`: 1,079 problems, as
before (none about the inventory or leaks).

## Next session

The contract and API sections of SPEC.md, starting with:
- plugin key, module keys and types;
- REST paths and payloads, servlets, stored data and persisted names;
- then the 417 public API types and their signatures (3–5 sessions).

Evidence may now cite classes of the internal libraries directly.
