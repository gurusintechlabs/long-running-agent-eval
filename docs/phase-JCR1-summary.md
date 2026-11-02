# Phase JCR1: change request 1 (jira-re)

**Date:** 2026-11-02 · **Branch:** `jira-re` · **Design:** `docs/jira-re-design.md` §7.2, §5 · **Previous:** JC6

This phase wrote the stage-5 change request, the last blocker in `check_spec`. No API spend, and no agent run.

**Exit check (stated at the start):**
1. `spec-changes-1.md` replaces the placeholder and covers only pilot claims. Each entry is checked against the code, new
   ids can't clash with existing ones, and no internal names leak.
2. Every other place in the spec that repeats a fixed behaviour is covered by an entry or found not to need one.
3. `check_spec` reports 0 problems and scans the change file for leaks.
4. A new hidden check sees stage 5.
5. `pytest` and the jira-re `-m local` tests are green.

**Result: met.** See "Tests" for the numbers.

## Owner rulings, 2026-11-02

- **Fix the real faults only.** 11 of the pilot's 26 suspected-bug claims change. C-4194, unflagged, changes with them (see below). The
  other 15 flagged claims stay contract, as stated.
- **No permission tightening: honour the original.** C-2080, C-4064, C-4069, C-4083, C-4090, C-4099 and C-1898 stay as specified.
- **No audit** of the 98 medium-confidence claims. The accuracy pass stays after the pilot.

## What the change request says

Seven changes replace 12 claims with C-9001 to C-9012. Nothing changes in a REST path, payload, stored format or public signature.

| change | replaces | new | module(s) |
|---|---|---|---|
| A repeated apply rule is not a cycle | C-1022, C-2085 | C-9001, C-9002 | `structure-manager`, `permissions-calculator` |
| A failed copy leaves no structure behind | C-1041 | C-9003 | `structure-manager` |
| No deleted event for an unknown id | C-1044 | C-9004 | `structure-manager` |
| Clearing a user's cache clears that user's cache | C-1430 | C-9005 | `favorite-manager` |
| A fallback answer is not cached | C-1573, C-1580, C-1585 | C-9006 to C-9008 | `forest-permissions-cache`, `project-scope-cache`, `sub-task-issue-cache` |
| The security filter does not hide failures | C-4192, C-4193, C-4194 | C-9009 to C-9011 | `security-filter` |
| Property keys are read as they are written | C-1464 | C-9012 | `property-service` |

**Spread on purpose, because that is what stage 5 measures:** three of the changes touch several claims, in up to three modules, so
each one is only done when the implementer finds every affected place.

**Checked in the code by me, each one:**
- **Apply rules:** the chain is only ever added to, and each of the structure's own rules starts a new one. Both examples traced by hand.
- **`copyStructure`:** there is no clean-up after the save.
- **`deleteStructure`:** the event is published unconditionally.
- **Favourites:** `clearUserCaches(String)` is overridden too, and it ignores its argument, so C-9005 covers both variants. C-1429 stands,
  because erasure invalidates the right key directly.
- **Fallback answers:** exactly three caches share the path, and all three are in the change. The unusable-index answer reaches the
  cache as well, so "not cached" covers it, as C-1580 and C-1585 imply.
- **Security filter:** one `catch` covers all three paths. **C-4194 is not flagged as a suspected bug, but it had to change with the
  other two**, or the filter would rethrow on HTTP paths and still swallow on the other.
- **Property keys:** `invalidate(key)` had to trim as well, or `invalidate(" a")` would no longer reach the entry that `getString(" a")`
  reads. C-9012 says so.

**Left alone after checking:** C-2084 (cycles are still skipped), C-1572 (fallback answers don't change), C-1043, C-1463, C-1467.

## What was built

Test-first; 15 new test cases, and one existing test extended.

- `analyst/changes-1.json`: the source. `analyst/build_changes.py` (`--check`) generates `spec-changes-1.md` and `hidden/changes-1.json`.
  It refuses a low or repeated id, an unknown or inactive claim, a claim of another module, and a module outside the pilot.
- **New ids start at C-9001.** They stay out of `claims.jsonl` and `claim-ids.json`, because the implementer must not see them before stage
  5. `build_claims.py` is at C-8134, so they can't clash soon. A new claim's evidence is that of the claim it replaces.
- **`check_spec` now leak-scans `spec-changes-1.md` like `spec/`,** since it reaches the agent. Before, it only looked for the placeholder.
- **Hidden t09** (static, stages 5+) checks each of the 12: a test named after the new id, no test named after the old one, both ids in
  `analysis/CHANGES-APPLIED.md`, and the swap in `rewrite_map.json`. It picks up where t08 stops. On the real jar: skipped at stage 4,
  12 failures on an unapplied workspace at stages 5 and 6, and 12 passes on an applied one.
- `stage5.md` now matches: it replaces, no longer retracts or adds, and asks for both ids in the report.

The seed is unchanged (`2d07cbb2`): the change request is not in it.

## Tests

All on the final code, seed `2d07cbb2`:

- **`pytest`:** exit 0. 1,774 tests, 0 failures, 0 errors, 1 skipped (`test_binds_loopback_only`, the known one).
- **`pytest -m local -k jira`:** exit 0. 4 tests, 0 failures. The rest of `-m local` was not rerun, because only jira-re fixtures, docs
  and tests changed.
- **`check_spec.py`:** 0 problems. `build_changes.py`, `build_pilot.py` and `prepare_seed.py --check` are all up to date.

**A real bug the unit tests missed:** the first t09 errored on any jar without the pilot's modules, because `need_module` raises for an
unknown key instead of skipping. Only the `-m local` synthetic-plugin test caught it. t09 now skips those changes, and I reran both suites.

No `api`-marked test or real agent run was made.

## Unresolved, and proposals

1. **Stage 5 holds no real spec errors,** by ruling. Every entry is an owner-decided fix, so a run measures how well the agent applies a
   revision, not how it recovers from a wrong spec. Design §5 hoped for the second as well.
2. **t09 reads names only, like t08.** It can't tell whether a fix works. Behaviour per claim is still tier 3.
3. **The apply-rule fix has a cost the original didn't.** With the chain shortened, structures that apply the next one twice over many
   levels are walked exponentially. Only someone with `ADMIN` on those structures can set that up.
   **Proposal:** none for the pilot; a limit would be a new behaviour, for a later change.
4. **A level can change after replacing the original.** Structures with repeated apply rules give a different level. Change 1 tells the
   implementer to say so in `RELEASE.md`.
5. **`CHANGES-1.md` covers the pilot only.** The 307 suspected bugs outside it are untouched, and need their own ruling before a
   full-scope run.
6. **Still open from earlier phases:** the JS2 cloud-migration question, whether `GenericItemHistoryManager` stays contract, new hidden API
   tests from the claims, and the proposed metric for `SUSPECTED-BUGS.md` coverage.

No spec decision (D-n) was changed. Nothing is committed yet.

## Next session

The pilot run itself. It needs a spend estimate and the owner's approval first.
