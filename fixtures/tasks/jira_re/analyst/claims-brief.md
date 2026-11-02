# JC6 helper brief: behavioural claims for the plugin's user interface

Repo: /Users/tonylee/Documents/coding/longhorizon_testing (branch jira-re). You are an analyst helper in a
clean-room reverse-engineering project. Another engineer (an AI agent) will re-implement this Jira plugin
**from our spec alone** and never sees the original code. You write **claims**: one testable behaviour per
claim, in your own words. The implementer writes a test per claim (named after the claim id) against its own
code.

This session covers the plugin's **user interface**: 84 web-resources (the grid and its panels, dialogs, pages,
admin screens, third-party bundles), 24 web items, 12 web sections, 4 web panels, 2 gadgets and the keyboard
shortcut. Everything behind the UI is already claimed: the API types, all 211 components, 234 extension modules
and the REST, pages and hooks (`rest-v1`, `rest-v2`, `rest-cfd`, `ww-structure`, ...). Build on them, and refer
to them by module key or REST path. The goal is that the UI can be **rebuilt, working the same for its
users**, from the spec, with no access to the original: what is on each screen, what every control does, what
is sent to the server, what is shown back, and every state in between.

## What is contract for the UI
- **The module key, type and descriptor element** (attributes and children; `inventory.json` under `contract`):
  web-resource dependencies and contexts, web-item sections, weights, labels and links, conditions.
  A web-item's or web-panel's **conditions** are stated exactly, in behavioural terms: when is it shown.
- **Everything the browser exchanges with the server.** Each REST call the UI makes (method, path as in SPEC.md
  §1.3, query and body fields, when it is sent, how often, what the UI does with each answer and each error)
  and each page URL it opens or links to. The REST side is contract, so the UI must use it exactly.
- **URLs users keep.** Page URLs, their query parameters and URL fragments, and anything else a bookmark or a
  shared link carries: written exactly.
- **The browser-side API** (SPEC.md §1.7 leaves it to these claims): what companion apps call. The global
  `window.almworks.structure.api` and the AMD ids under `structure/api/`, with their members, and how registered
  columns, details providers, generators and effectors plug in. Helper u2 owns this; those names are exact.
- **Keyboard shortcuts and mouse gestures,** exactly.
- **User-visible English text** of labels, menu entries, buttons, titles and messages, exactly, for short
  strings. Resolve each i18n key in `analyst-work/jar/i18n/StructureMessages.properties` (or `CfdMessages`).
  State the text, not the key, unless the key is stored or sent to the server.
  **Long prose is not copied**: marketing and welcome text, help text, tour and hint paragraphs, template
  descriptions. Say what it tells the user, in your own words, and how long it is roughly.
- **Numbers that shape behaviour:** page sizes, debounce and poll intervals, retry counts, limits, default and
  minimum widths, thresholds. State them with their values.
- **NOT contract, never named in a claim:** AMD ids outside `structure/api/` (for example anything under
  `structure/widget/`), `@almworks/...` ids, JS file and template paths, JS class, function and variable names,
  CSS class names, DOM ids and HTML structure, Velocity macro names, browser-storage key names. A validator
  rejects internal module names and paths. Say what is remembered, per what scope and for how long; the
  storage key is the implementer's.
- **Not described:** pixel layout, colours, fonts, images. Describe arrangement only as far as a user sees it
  ("the toolbar sits above the grid; the panel can be swapped to the right"). A claim says what is there and
  what it does, never how it is drawn. Stylesheet-only modules get one or two claims: what they cover, plus
  anything behavioural (dark theme, print rules, hover reveals).
- **Third-party bundles** (`jquery`, `jquery-ui`, `react`, `momentjs`, `tslib`, `c3`, `stacktrace.js`, `uikit`,
  `vendors`, `fonts`): do not describe the library. Their key, type and dependencies are contract; which library
  or version fills them is the implementer's choice. Claim what the plugin needs from each one and any isolation
  it does, for example that it must not disturb Jira's own global `$`, `_`, `React`.

**Vendor identity (owner rules, SPEC.md §1.1, §1.8).** The replacement is not the vendor's product. Never claim
vendor branding, logos, the product name as a brand in marketing text, or links to the vendor's site, docs,
support, Marketplace listing or feedback forms: say "a link to the plugin's documentation", and the implementer
provides its own. Nothing is sent to the vendor: feedback, analytics and error reports that would go there stay
out, and you say so. `POST /statistics/record` is local and stays.

**Licence rules (owner rules).** No licence checking. Any licence banner, dialog, page or state claims the fixed
answer only ("licensed, valid, not expiring"), which means licence warnings, banners, expiry messages and
read-only modes **never appear**. Do not read or describe licence, certificate, serial or Marketplace logic, in
the UI either. Check SPEC.md §1.1 and §1.8 and INVENTORY.md §5, and follow them over the code.

Jira version: the pinned platform is **Jira 9.12**. Where code or a descriptor has variants for Jira ranges,
claim the 9.12 one. Integrations (Jira Software, Advanced Roadmaps, Tempo, Assets, Service Management, Confluence,
ScriptRunner) are claimed for when the other app is present and for when it is absent.

## Which module a claim belongs to
`module` is the key from your `modules.txt`. All of the structure widget's code is one web-resource, `widget-bare`,
so claims about the grid, its panels and dialogs use `module: "widget-bare"`, by several helpers; `scope.txt`
tells you which part is yours. A page's script belongs to its own web-resource. A server-rendered page's
**screen** (what its template shows and how its form behaves) is claimed under the page's web-resource when it
has one, otherwise under `ww-structure`. JC5 already claimed each page's parameters, permissions, redirects,
errors and data: search `claims.jsonl` for the alias, and do not repeat those. Add the screen: what is shown
where, conditional parts, fields with their labels and defaults, what is disabled when, what each button does.
Generator, effector and synchronizer forms are claimed under the module they configure.

## Who claims what, between helpers
- **A file you own is yours whole.** A split AMD file can also hold code that follows the module (a large
  configuration object, a decorator, a page's start-up). If it is in your file, you claim it.
- **The feature's owner claims the request.** Whoever owns the control or dialog claims when its REST call is
  sent, with what, and what the UI does with the answer. The owner of the shared data and transport code claims
  only the general rules: retries, error handling, caching, batching.
- **The feature's owner claims what is remembered:** what, per what scope, for how long. Read the storage code for
  that. The storage code's owner claims only the general rules of browser storage.
- **Calls to another app's REST API** (a companion app, Jira's own REST) are claimed as such: say which app, and
  what happens when it is absent. They are not reported as gaps in SPEC.md.
- Some overlap at the edges is fine. A gap is not, so when in doubt, claim it.

## Your inputs
- `modules.txt` in your own scratch folder (path in your prompt): each module's key, type, descriptor element,
  purpose, its resources, and the claim ids already mentioning it. `scope.txt` beside it: **the sources you
  own** (AMD ids, JS files, templates). Read every one of them.
- **Formatted JS: `analyst-work/uivf/`.** The originals are minified; this tree is the same code run through a
  formatter, keeping jar-relative paths. Local variable names are one letter, but property names, method names,
  strings and i18n keys are real.
  - The widget, split per AMD module: `analyst-work/uivf/split/js/structure/structure-widget/<AMD id>.js`
    (`@almworks/...` drops the `@`).
  - Other bundles the same way under `analyst-work/uivf/split/js/structure/<bundle>/`.
  - Single files: `analyst-work/uivf/js/structure/...`, `analyst-work/uivf/gadgets/`, `analyst-work/uivf/fe/`.
- **Originals, `analyst-work/jar/`:** `atlassian-plugin.xml`, Velocity templates in `templates/`, gadget XML in
  `gadgets/`, i18n in `i18n/`, `css/`. Type declarations `*.d.ts` under `js/structure/` help you read the widget.
- The server side, when you must see what an answer means: Vineflower source in `analyst-work/vf/`, internal
  libraries in `analyst-work/libvf/<lib>/`, the public API in `analyst-work/apivf/`.
- The spec already written, which your claims must agree with:
  - `fixtures/seed_jira_re/spec/SPEC.md`: module table (§1.2), REST (§1.3), pages (§1.4), persisted names
    (§1.6), front-end extension points (§1.7), §1.1 and §1.8 (no licence, no vendor contact).
  - `fixtures/seed_jira_re/spec/API.md`: the Java API.
  - `fixtures/seed_jira_re/spec/claims.jsonl`: existing claims. Search by module key, REST path and page alias.
    Do not repeat them; build on them.
  - **Check every REST call you find against SPEC.md:** parameter names, body shape, response fields the UI
    reads. Report each mismatch. If API.md or SPEC.md is wrong, say so in your report; do not edit them.
- **Never read `analyst-work/central-src/`, and keep it out of every search** (search `uivf/`, `jar/`, `vf/`, `libvf/`,
  `apivf/` by name, or use `grep -r --exclude-dir=central-src`). It is the vendor's source with javadoc. Copying
  from it is the one thing that breaks the clean room. Never copy code, HTML or CSS into a claim either.

## Your output: exactly one file
`fixtures/tasks/jira_re/analyst/claim-notes/<group>.json`, the only file you write in the repo. Scratch
scripts or notes go in your own scratch folder only.

```json
{"claims": [
  {"key": "<group>/<module-key>/<short-slug>",
   "module": "<module key from modules.txt>",
   "api": null,
   "behaviour": "One behaviour, testable from outside, in plain English.",
   "confidence": "high|medium|low",
   "evidence": ["amd:structure/widget/SomeModule", "templates/structure/manage/x.vm"]}
 ]}
```
- `module` is the module key; `api` is null.
- `evidence`: one or more of: `amd:<AMD id>` for widget and other AMD code; a jar-relative path (`js/structure/x.js`,
  `templates/structure/x.vm`, `gadgets/x.xml`, `atlassian-plugin.xml`); `fq.Class` or `fq.Class#method` for Java.
  Never a `uivf/` path. Harness-side only, never shown to the implementer. **Coverage is checked from your
  evidence: every AMD module, JS file and template in `scope.txt` must be cited by at least one claim.** If one
  has nothing to say (a constant table, a thin wrapper), cite it on the claim it serves.
- `confidence`: `high` = read in the code with its edge cases; `medium` = clear, but an edge depends on code
  you could not fully follow (or on Jira or the browser at run time); `low` = inferred.
- Keys are permanent ids once built. Make them descriptive and stable.

## What a good UI claim is
- **Given / when / then, from outside.** "Given this state, when the user does this, the UI sends this request /
  shows this / changes this", or "this control is shown only when ...". Good subjects: what a screen shows in each
  state (loading, empty, error, no permission, read-only, archived); each menu entry with its label, when it is
  there, when it is disabled and what it does; each dialog with its fields, defaults, validation, buttons, and
  what happens on success, failure and cancel; selection, focus, expansion, scroll and edit rules; keyboard and
  drag-and-drop rules; what is remembered between visits and for whom; how the UI keeps in step with the server
  (polling, subscriptions, optimistic updates, undo, conflicts, retries, going offline); which formats it
  parses and displays (dates, durations, numbers, with worked examples).
- **Specific enough to test without a human looking at it.** Prefer logic with inputs and outputs: "a duration of
  90000 ms shows as 1m 30s", "with 3 rows selected the entry reads Delete 3 rows", "typing pauses for 300 ms before
  `GET /x?q=` is sent, and an older answer is dropped". Avoid "looks", "nice", "appropriate".
- **Your own words, behaviour only.** No code, no pseudo-code transcribing method bodies, no internal names. Never
  copy javadoc phrasing, comments, or HTML.
- **Uniformly deep, and complete.** The implementer has nothing else: a behaviour you skip does not exist in the
  rebuild. Typical: 1–3 claims for a thin wrapper, a dependency-only resource or a web item; 5–15 for a small page
  script, dialog or column type; 15–50 for a large one (the grid, cell editing, the panel header, the view
  dialog, the transformations banner, the formula editor). Don't pad, and don't skip responsibilities. Merge
  repetitive cases into one claim with a table of values, in words, rather than many near-identical ones.
- **Delegation:** if the behaviour belongs to a module that already has claims, refer to it by key.
- **Describe the original faithfully, bugs included.** Where it looks like a bug, state what it does, add
  "(as the original does)" and list it in your report. Prefer `medium` if unsure it is intended. That exact
  phrase flags the claim `suspected_bug` for the implementer, who must check it; use it only for suspected bugs.
- **Behaviour that needs a running browser or Jira** still gets a claim, stated as what the UI asks for and what it
  does with the answer. Say what is not determinable rather than invent it.

## Validate before you finish
    .venv/bin/python fixtures/tasks/jira_re/analyst/build_claims.py --validate fixtures/tasks/jira_re/analyst/claim-notes/<group>.json
It must print `ok`. It catches unknown modules, bad evidence and leaked internal names. Do **not** run
`build_claims.py` without `--validate`, and don't run `check_spec.py`, `build_api.py`, `prepare_seed.py` or
anything that writes: other helpers are working in parallel.

## Report (your final message, short)
- claims written per module; responsibilities left unclaimed, and modules with no behaviour of their own, if any;
- suspected bugs in the original (module, behaviour);
- disagreements with API.md or SPEC.md, including REST calls that don't match (where, what is wrong);
- behaviours you could not determine;
- anything in `scope.txt` you did not cite (there should be nothing).
