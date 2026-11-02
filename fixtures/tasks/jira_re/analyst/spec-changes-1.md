# Specification corrections: change request 1

These corrections were decided by the product owner after the analyst's review of the suspected bugs. Each change
replaces claims of `spec/claims.jsonl`. A replaced claim stops being contract, and the new claim, given here in full,
takes its place under a permanent id of its own.

- The behaviour below deliberately differs from the original.
- Where this file differs from `SPEC.md`, `API.md` or `claims.jsonl`, this file wins.
- Claims not named here are unchanged. That includes every other claim with `"suspected_bug": true`: they stay contract,
  as stated.
- No REST path, payload, stored format or public signature changes.

## Change 1: a repeated apply rule is not a cycle

A structure stayed remembered after its rules had finished, so a later rule that repeated it was skipped as if it closed a cycle, and a user's level depended on an unrelated earlier branch. Real cycles are still skipped (C-2084 is unchanged). Structures with such rules can give a different level than the original did: say so in the install notes of `RELEASE.md`.

### C-9001 (`structure-manager`), replaces C-1022

For other users the level starts at `NONE` and the structure's rules are applied in list order: a `PermissionRule.SetLevel` whose subject matches the user replaces the current level with the rule's level (a later matching rule overrides an earlier one, including lowering it); a non-matching rule leaves it. A `PermissionRule.ApplyStructure` applies the rules (not the owner) of the referenced structure at that point, recursively, continuing from the current level; a reference to a missing structure or to the structure itself is skipped. A nested reference is skipped only when it closes a cycle, that is when it names a structure whose rules are still being walked; a structure stops counting as soon as its rules are finished, so a repeat in a later branch is applied again. Example: S1=[apply S2], S2=[apply S3, set NONE for anyone, apply S3], S3=[apply S4], S4=[set VIEW for anyone]: S1 gives VIEW, as S2 alone does. A null rule is skipped; a null resulting level is reported as `NONE`.

### C-9002 (`permissions-calculator`), replaces C-2085

Inside one level computation the chain of apply rules holds exactly the structures whose rule lists are being walked at that moment: a structure leaves it when its rules are finished. So an apply rule pointing at a structure that was applied and finished earlier in the same branch is applied again, and only a rule pointing at a structure still being walked is skipped (C-2084). Example: S1 = [apply S2]; S2 = [apply S3, set NONE for anyone, apply S3]; S3 = [apply S4]; S4 = [set VIEW for anyone]. The level on S1 is VIEW, the same as the level on S2 computed directly. A real cycle is still skipped: with S1 = [apply S2], S2 = [apply S3], S3 = [apply S2, set EDIT for anyone], the level on S1 is EDIT.

## Change 2: a failed copy leaves no structure behind

A forest copy that failed left a new structure with an empty forest, which the caller had no way of knowing about, since the call threw.

### C-9003 (`structure-manager`), replaces C-1041

`copyStructure(id, newOwner, copyPermissions)` performs the same checks, saves the copy (as `saveChanges()` would, with the same permission and owner checks) and then adds the source's current stored forest (its stored rows, generators not run) at the top level of the copy's empty forest, acting as the current user and subject to the same checks and limits as any forest change of that structure. Each copied row gets a new row ID; rows of structure-owned items (generators, effectors, folders) refer to new item copies owned by the new structure. The returned structure is the saved copy. If copying the forest fails, the copy is removed and the exception is thrown, so no new structure stays behind. The removal does what `deleteStructure` does for an existing structure, `StructureDeletedEvent` included, and needs no right of the current user on the copy; like `deleteStructure` it leaves item copies already made alone. If the removal itself fails, that failure is logged as an error and the original exception is still the one thrown.

## Change 3: no deleted event for a structure that never existed

Under security override, deleting an unknown id published a `StructureDeletedEvent`, and listeners then cleaned up after a structure that was not there. This overrides the words "then publishes a structure-deleted event" in `API.md` for an unknown id only.

### C-9004 (`structure-manager`), replaces C-1044

Under security override, `deleteStructure` of an ID with no stored structure succeeds, deletes nothing and publishes no `StructureDeletedEvent`: the event is published only when a structure row was actually deleted. For an existing structure C-1043 applies unchanged.

## Change 4: clearing a user's cache clears that user's cache

The given user was ignored and the current user's favourites were dropped instead, so the given user's cached favourites could stay stale.

### C-9005 (`favorite-manager`), replaces C-1430

CachingComponent.clearUserCaches(user) and clearUserCaches(userKey) drop the cached favourites of the given user, whoever the current StructureAuth user is and also when there is none, and leave other users' cached favourites alone. clearCaches() drops all cached favourites and popularity counts.

## Change 5: a fallback answer is not cached

When a search failed or the index was unusable, the fallback answer stayed cached until the issue changed or the cache was cleared, so one bad moment could hide issues long after the index recovered. The fallback answers themselves do not change (C-1572 still holds). This applies to all three caches.

### C-9006 (`forest-permissions-cache`), replaces C-1573

Results of `collectInvisibleIssues` are cached per user key (anonymous under an empty key); all calls with the security override share one cache regardless of user. An issue's cached result is dropped when `ItemTracker` reports a change to that issue. An answer that comes from a failed search or an unusable index (all issues searched for are reported as invisible, C-1572) holds for that call only and is not cached, so the next call searches for those issues again. Results already in the cache are still used.

### C-9007 (`project-scope-cache`), replaces C-1580

If the index search fails with a `SearchException`, all issues being checked are reported as out of scope. If the index is unusable (full reindex running or inconsistent), nothing is reported for them. Either answer holds for that call only and is not cached, so the next call reads the index for those issues again. Results already in the cache are still used.

### C-9008 (`sub-task-issue-cache`), replaces C-1585

If the index search fails with a `SearchException`, all issues being checked are reported as sub-tasks; if the index is unusable, none are. Either answer holds for that call only and is not cached, so the next call reads the index for those issues again. Results already in the cache are still used. `clearUserCaches(user)` does nothing.

## Change 6: the security filter does not hide failures

The filter logged every exception and dropped it, so a failed policy gave an empty response, and failures further down the chain never reached the container's error handling. All three paths change together. `partitioned-cookie-header-filter` is a different module and does not change.

### C-9009 (`security-filter`), replaces C-4192

When computing or setting the policy before the chain throws an `Exception` (for example when application links cannot be read), it is logged as an error (`Unexpected exception in servlet filter`), the chain is not called, and the exception leaves the filter, so the request ends in the container's error handling and not in an empty response. `IOException`, `ServletException` and unchecked exceptions are rethrown unchanged; any other checked exception is wrapped in a `ServletException`.

### C-9010 (`security-filter`), replaces C-4193

An `Exception` thrown by the chain, `IOException` and `ServletException` included, or by a later policy update, is logged as an error (`Unexpected exception in servlet filter`) and then leaves the filter as C-9009 says, so the container's error handling sees it. An `Error` does propagate.

### C-9011 (`security-filter`), replaces C-4194

A request or response that is not HTTP goes down the chain unchanged. An `Exception` from that chain is logged and leaves the filter as C-9009 says.

## Change 7: property keys are read as they are written

Writes trimmed the key and reads did not, so a value written under ` a` could not be read back under ` a`.

### C-9012 (`property-service`), replaces C-1464

The getters (getString, getBoolean, getLong) and invalidate(key) remove leading and trailing whitespace from the key, as set does: after set(" a", "x"), getString("a", null) and getString(" a", null) both return `x`, and invalidate(" a") drops the cached value of `a`. A key that is blank after trimming finds nothing: a getter returns its default and does not throw (the refusal in C-1463 applies to writes only).
