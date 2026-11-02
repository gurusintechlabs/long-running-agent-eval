# Phase JC6: claims session 6, the user interface (jira-re)

**Date:** 2026-10-30 · **Branch:** `jira-re` · **Design:** `docs/jira-re-design.md` §7.2, §7.4 · **Previous:** JC5

The last module-claims session. It wrote the claims for the 127 UI modules: 84 web-resources, 24 web items, 12 web
sections, 4 web panels, 2 gadgets and the keyboard shortcut. It also specified the browser-side API that SPEC.md §1.7
had deferred. No API spend.

**Exit check (stated at the start):**
1. **Content.** All 127 UI modules have active claims. Every plugin-owned JS file, AMD module and Velocity template is
   cited by at least one claim's evidence, checked by script. The browser-side API is specified.
2. **Leaks and copying.** `--validate` passes for every notes file, `check_spec` finds no leaks, now including internal
   JS names, and no vendor prose, HTML or CSS is copied.
3. **Spec errors.** Mismatches helpers found between the front end and SPEC.md are checked and fixed, and the generated
   files rebuilt.
4. **Green.** `pytest` and `-m local` pass, every `--check` mode is up to date, and the seed is re-pinned. `check_spec`
   ends at one problem, the change-request placeholder.

**Result: met,** with one limit on what "met" says. Item 1 proves each source was cited, not that each claim is right.
An audit of a random sample found 4 wrong claims in 85 (see "How accurate the claims are").

`check_spec`:
- 8,134 claims (2,766 new);
- modules with an active claim: 608 of 608;
- 1 problem: the change-request placeholder.

## How accurate the claims are

A fresh agent, given the code but not the helpers' reasoning, checked 85 claims against the original: 5 drawn at random
from the high-confidence claims of each of the 17 groups.

| verdict | claims |
|---|---|
| correct | 81 |
| wrong | 4 |
| unverifiable | 0 |

**That is 4.7% wrong (95% interval roughly 1% to 12%).** Applied to the 2,500 high-confidence claims of this session, it
suggests about 120 wrong ones, and possibly between 30 and 300. The sample is small, so treat this as an order of magnitude.

All four were an edge or condition stated wrongly, not an invented behaviour. I confirmed each in the code and fixed it,
along with one claim the audit called misleading (C-5430):
- C-5832: the details panel's debounce. A burst loads the first row and the final row, not only the final one.
- C-7153: an upload error marker is not cleared by retrying.
- C-6579: the 'Other Defaults' section has no explanatory note.
- C-8039: Tab cycles the new-issue fields whatever the summary holds; only Enter needs it empty.

Three more wrong high-confidence claims were found outside the audit: the view menu's 'Previous View' entry, which does
not exist, and the keymap's Space and Home/End in one of two overlapping sets. These are fixed too.

**Earlier phases have no such measurement.** Nothing here says whether their rate is higher or lower.

## What was built

**Formatted front-end source, `analyst-work/uivf/`** (git-ignored, like `vf/`). All UI code in the jar is minified, and
no formatter was installed. Prettier 3.3.3 was installed in a scratch folder with install scripts off, and it formatted
the 98 plugin-owned JS files with no parse failures. The two large AMD bundles were split into 487 files, one per module.
The widget is 52.7k formatted lines in 353 modules. Local variables stay one letter, but property names, strings and
i18n keys are real. Third-party minified libraries were left out. The script was a one-off in the scratch folder.

**Tooling** (test-first; 3 new test cases):
- **Evidence.** `Reference.resolve` in `hidden/_support.py` now accepts a jar entry (`js/x.js`, `templates/x.vm`) or
  `amd:<id>`. UI behaviour has no Java class to cite, and this made coverage checkable from evidence.
- **Leak scan.** `check_spec.py` and `build_claims.py` now flag non-contract AMD ids, their CamelCase simple names, and
  script and template paths. `contract-classes.txt` gained the 14 `structure/api/` ids, plus 3 words that coincide with
  JS names (`DateField`, `ItemId`, the `widget-i18n` location).

**Helper brief, JC6 version** (`analyst/claims-brief.md`). It sets what is contract for a UI:
- **Contract:** descriptor attributes and conditions, everything the browser exchanges with the server, URLs users keep,
  the browser-side API, keyboard and mouse gestures, numbers that shape behaviour, and short user-visible English text.
- **Not contract, never named:** other AMD ids, file paths, JS names, CSS classes, DOM ids and browser-storage keys.
- **Not described:** pixels, colours, fonts, images, and long prose, which is paraphrased.
- **Third-party bundles:** key, type and dependencies are contract, and which library fills them is the implementer's.

**The claims** came from 17 helpers. `u8-views` ran first as a pilot, and I read its output before launching the rest.
It exposed a gap: a split file can hold code after its module (14 files do, such as a 535-line client configuration
object). The brief gained a section on who claims what between helpers.

| group | scope | claims | suspected bugs |
|---|---|---|---|
| u1-widget-shell | start-up, layout, UI state, URLs, AJAX rules, statistics, umbrella resources | 156 | 4 |
| u2-browser-api | browser API, attribute registry and selector, column edit panel | 122 | 2 |
| u3-data-sync | forest model, polling, subscriptions, value cache, perspectives, view loading | 202 | 5 |
| u4-edit-queue | upload queue, undo, history, clipboard, drag and drop, effector dialogs | 139 | 8 |
| u5-grid | grid, keyboard and mouse, column header, forest panel | 252 | 7 |
| u6-header-toolbar | panel header, structure selector, toolbar, Add Column | 142 | 4 |
| u7-transforms | transformations, automation UI, 57 generator forms | 160 | 10 |
| u8-views | view dialog and model, user settings, client configuration | 124 | 3 |
| u9-editors | inline editing and creation, pickers, planning task dialog | 179 | 9 |
| u10-columns-a | main, field, attribute, icons and other basic columns | 119 | 2 |
| u11-columns-b | formula, notes, progress, saved, Tempo and other advanced columns | 177 | 5 |
| u12-details | details panel, info dialog | 133 | 4 |
| u13-util-libs | shared utilities, third-party bundles, stylesheets | 101 | 8 |
| u14-integration | web items, sections and panels, gadgets, issue, Agile and project pages | 275 | 8 |
| u15-manage-create | Manage Structures, copy, Create wizard, printable, welcome | 208 | 10 |
| u16-admin | admin screens, banners | 140 | 6 |
| u17-sync-effector | sync and effector pages, emails | 137 | 7 |

- **Confidence:** 2,500 high, 266 medium, none low.
- **Length:** the median claim is 318 characters.
- **Suspected bugs flagged:** 102 new, 333 in all.

**Coverage, by my own script over the evidence:** all 127 UI modules have claims, and every source in the 17 `scope.txt`
files is cited (uncited: 0). Citation is not proof of reading: `u16-admin` deliberately did not read the four licence
sources (`license.vm`, `debug-license.vm`, `endOfLife.js`, `structure-upm.js`), and cites them on fixed-answer claims only.
`fe/vendors.js` is third-party and was only sampled.

**Scans, by script over the 2,766 new claims:**
- **Vendor names and URLs:** one hit, the legitimate label 'Group by Tempo Account'.
- **Markup or code:** 4 hits, all harmless (`<n>`-style placeholders and an example of tag stripping).
- **Verbatim bundle text of 10 or more words:** 156 claims. The 9 of 20 words or more are functional warnings and
  confirmations, which the brief asks for exactly. None is marketing or help prose.

## Spec text corrected (checked in the code by me)

- **SPEC.md §1.7** now lists the browser API: `window.almworks.structure.api` with its 18 members, `window.namespace` and
  the 14 `structure/api/` AMD ids. It also says the rest of the front end's names are not contract, and how the
  third-party bundles work.
- **Shape `quick-transform-button`:** `color` is one of six colour-picker values, not a CSS colour.
- **`attribute-subscription-update.full`:** the client merges a full update; it does not discard what it had.
- **Trailing slashes (§1.3 conventions):** the front end calls 6 paths with one, and they must answer the same. This
  rests on JAX-RS matching rules, not on a test against a running server.
- **`extensions`:** the key `licensed` in an entry is the companion app's own flag, which the plugin neither computes nor
  checks.
- **C-5090:** the ClearStructureCaches form posts `confirm=true`, not `execute=true`.

**Helper doubts I checked and rejected:**
- **C-4513 and C-4514 are right.** `noContent()` is the plugin's own helper and answers 200 with the empty object.
- **The extra `signature` and `atl_token`** on printable and Excel URLs need no spec change: neither server side reads them.

**Suspected bugs I confirmed in the code:** the Structure gadget's picker wired to `trainingStructureId`, the setup
guide's `POST` to a `PUT` endpoint, `count` where the server reads `limit`, and the decision drop-down reading only one
character. The other 98 flags rest on the helpers' reading.

**Moved between modules:** the 11 email claims went from `ww-structure` to `mail-sender` and `perspective-mail-sender`.

## Owner rulings, 2026-10-30

**UI claims are tested in a real browser.** I tried both options. Rhino has no DOM, so **Playwright 1.49.0 with jsoup 1.23.1
replaces the Rhino proposal**, in JUnit. `stage2.md` now says so, and `ENVIRONMENT.md` tells the implementer how.
- `prime_maven_repo.py` primes both, and installs Playwright's pinned headless Chromium 131 into `~/lrae-tools/re/browsers`
  (170 MB, read-only). Chrome on the host updates itself, so it could not be pinned (rule 4).
- `m2.manifest` now hashes the browser as well: `92915b72`, which is 126 added files, none changed or removed.
- `build.sh` points Playwright at that browser, and priming ends with a browser test. It also passed in a copy of the seed with a
  scrubbed env, offline, using the `pom.xml` lines `ENVIRONMENT.md` gives.
- There is no running Jira: tests use the implementer's own stand-ins for Jira's page objects, with REST replies faked by
  `page.route`. A claim that needs a real Jira page goes in `analysis/UNTESTED-CLAIMS.md` with the reason.

**`info-popup` does not lead to the vendor.** All `links` values are null, so the reply keeps its keys and its four entries, and
the popup rows have no links and no 'Try it' (C-4721, C-5947, C-5948). The rows, including 'not installed' ones, stay. The
formula editor's documentation links are the implementer's own or null (C-1940, C-2028). The `http://structure.almworks.com/syndication/...`
activity-stream IRIs stay, because they are identifiers and nothing fetches them.

**The word Structure.** I read "fix the word" as: the replacement must not show the vendor's product name. The word stays where it
is the plain noun.
- Text that names the product now says `<product>`, the replacement's own display name, in 211 claims (297 places) and in
  the inventory names, labels, SPEC.md and API.md. The rule is in SPEC.md 1.1 and `spec/README.md`.
- The noun stays: 'Delete Structure', 'Default Structure', 'Structure ID', 'Structure with id {0}...'. So do the plugin key, module
  keys, REST paths, i18n keys, class names and the companion apps' names.
- Claims' own prose may still say "the current Structure user": that is description, not text to show.
- `analyst/product-name-phrases.txt` lists the 97 phrases I rewrote, and `check_spec.py` now fails on any of them, or on a vendor address,
  anywhere in `spec/`. The split between product and noun was my reading of each string, so a few calls can be argued; a missed one
  is covered by the rule.

## Pilot scope, owner decision 2026-11-01

The first run covers **86 modules and 748 claims**: the groups core-model, persistence and permissions-security (85 modules, 667
claims), `structure-info` as a UI slice (23 claims), and the 58 API claims behind the 51 API tests. The spec stays whole.
- `analyst/build_pilot.py` writes `spec/PILOT.md`, `spec/pilot-claims.jsonl` and `hidden/pilot.json`.
- Stage 0 no longer says to read all of `spec/`, which is about 5 MB. Stages 2-4 and 6 and hidden t02 and t03 work on the pilot.
  The stage 1 skeleton (all 608 modules, all API signatures, t04, t05) and the API tests (t06, t07) are unchanged.
- New hidden t08 (stages 2-4) checks that each claim of a done module has a test named after its id, or an entry in
  `analysis/UNTESTED-CLAIMS.md`. It reads names only: it cannot tell whether a test is any good. Behaviour per claim is still tier 3.
- Stages 2-4 may now touch `analysis/**`, because they write `SUSPECTED-BUGS.md` and `UNTESTED-CLAIMS.md`.
- On the real jar and an empty workspace, each stage counts exactly 86 modules and fails or skips as it should.

**Before a real run:** `analyst/spec-changes-1.md` is still the placeholder, and the estimated spend needs owner approval.

## Tests

All run on the final seed `14af5563`, after the owner rulings below:

- **`pytest`:** exit 0. 1,752 tests, 0 failures, 0 errors, 1 skipped (`test_binds_loopback_only`: no resolvable hostname on
  this machine; nothing to do with this phase).
- **`pytest -m local`:** exit 0. 247 tests, 0 failures, 0 errors, 0 skipped. The Mac slept through most of this run, so it took
  about two days on the clock, for 6,955 s of test time. No test failed or timed out because of it.
- **`--check`:** `prepare_seed.py` and the claims, contract, inventory and API builds are all up to date.
- **`check_spec.py`:** 608/608 modules with an active claim, 8,134 claims, 163/163 endpoints, 186/186 AO columns, 3,997/3,997
  API members, 51/51 API tests. One problem remains, and it is expected: `spec-changes-1.md` is still the placeholder.

After the pilot change, on the final seed `2d07cbb2`: `pytest` exit 0, 1,759 tests, 0 failures, 1 skipped (the same one); the 4
jira-re `-m local` tests pass; `prepare_seed.py --check` and `build_pilot.py --check` are up to date. The full `-m local` suite was
not rerun after this change, because it touched only jira-re fixtures, docs and tests.

No `api`-marked test or real agent run was made.

## Unresolved, and proposals

1. **Decided 2026-10-30: how UI claims are tested** (see "Owner rulings" below).
2. **Owner decision needed: scope against the $200 pilot.** The implementer now has 8,134 claims in a 3.9 MB file, each needing a
   test. That pilot budget looks far short of it. This was already the direction of the owner's scope decisions, but the
   number is now real, and a pilot subset may be worth choosing before `spec-changes-1.md`.
3. **Decided 2026-10-30: vendor edges** (see "Owner rulings" below). 'Join the community', the support and Atlassian
   Answers links, the 'New Page' Marketplace promo and 'Go to the marketplace' stay out. The support ZIP stays, with no recipient.
4. **A full accuracy pass is an option.** The audit suggests about 120 wrong claims here, and earlier phases are
   unmeasured. Auditing every claim costs far more than the sample did (85 claims took one agent 325k tokens). **Decided 2026-10-30:** after
   the pilot, using which claims the implementer actually questions in `analysis/QUESTIONS.md`.
5. **Suspected bugs, for `CHANGES-1.md`.** The main ones:
   - **Lost edits:** a queued update replaces an older one for the same item even for different fields; a short
     `successfulActions` with no error stalls the queue; clearing one panel's queue during an upload stalls uploads.
   - **Wrong answers:** the decision drop-down applies the wrong answer from the 11th value on; a `full` forest update with an
     empty `formula` keeps old rows on screen; `/issue-field/options` sends `count`, which has no effect.
   - **Broken controls:** the Structure gadget has no live preview and `GET gadget/views` always sends `structureId=0`; the
     setup guide's statistics link stores nothing; the view dialog's Sharing tab is never selected; Quick Actions runs
     greyed-out entries; after a row's Revert is cancelled, `Revert selected` reverts that row.
   - **Stuck states:** several planning-task failures leave the dialog loading; a failed `structure/list` is never
     retried; a bad `s` value in the URL stops the widget starting.
   - **Text:** subject typo `Confict`; raw message keys shown in three places.
6. **Not determined** (medium):
   - Jira's own controls at run time: pickers, dialogs, the dirty-form check, and which AUI tooltips Jira 9.12 ships;
   - browser-dependent events, such as the mutation event for removed Jira banners;
   - whether a replacement can rely on what Jira does with a resource required by an absent app.
7. **Overlap between helpers.** The keymap is claimed twice, by u4 and u5, and now agrees. `export-structure-as-json`
   is claimed under both its own key and `widget-bare`. Overlaps I did not read side by side may still disagree.
8. **Copy similarity does not cover JS.** `lrae.cr.structural` and `lrae.cr.lexical` compare Java. Copying from the spec's
   exact texts is expected, but the metric would not see a leak of front-end code. **Proposal:** none needed unless the
   pilot's front end looks suspiciously close to the original, since the agent has no access to it.
9. **Still open from earlier phases:**
   - new hidden API behaviour tests written from the claims;
   - the other JS3 owner questions;
   - the proposed hidden metric for `SUSPECTED-BUGS.md` coverage.

No spec decision (D-n) was changed. Nothing is committed yet.

## Next session

`spec-changes-1.md` (it must replace the placeholder, the last `check_spec` problem), the last `prepare_seed.py`, then the
full run, which needs spend approval. Items 1 and 2 above should be decided first.
