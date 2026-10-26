# Phase U6, frontend: Specs editor and Review views

**Status:** built, tested, pushed on branch `ui-w2-specs` (from `ui-manager`). No API spend, no `claude`, no Python changes.
Backend reference: `docs/ui-api-specs.md`, `docs/phase-U6-data-summary.md`.

## Built (all under `ui/web/`)

* `src/api/specs.ts`, `src/api/review.ts` (typed, additive; exported from `src/api/index.ts`). `client.ts`: `DELETE` added to the method union.
* `src/components/ConfirmDialog.tsx` + `dialog.css` (shared modal: Escape, focus trap, focus return). Exported from the component index.
* `src/views/specs/`: `SpecsView` (list), `SpecEditor` (route `/specs/:name?source=draft|example`, `/specs/_new` for a blank spec), `SpecForm` + `fields.tsx` (schema-driven widgets), `formLogic.ts` (pure helpers), `yamlio.ts`, `useUnsavedGuard.ts`.
* `src/views/review/`: `ReviewView` (`/review` run overview, `/review/:runId` queue), `reviewLogic.ts`.
* Routes: `specs/:name`, `review/:runId` added; Specs and Review no longer "soon" in `nav.ts`.
* New dependency: `yaml` (package.json / lock), loaded on demand in its own chunk, core schema only.

### Specs
* List: drafts and examples, validity badge with first errors, 12-char hash, runtime/model, "real spend" marker (claude_code), mtime. Duplicate to draft (name dialog, 409 offers explicit overwrite), Delete draft (confirm), New from example, New blank, Launch link (`/launch?spec=<name>`) for valid drafts, search.
* Editor: form generated from `GET /api/specs/schema`: sections (collapsible all-advanced ones), labels, help, units, required markers (`required_if`), `visible_if`, notes with `when`, cross-field notes, defaults as placeholders, advanced fields in a per-container "Advanced (n)" panel. Widgets: text, textarea, number (integer step), single/multi select (chips), checkbox (shows default until touched), path (datalist from `/api/specs/paths`, filtered by file/dir), string_list (add, Enter adds a row, up/down, remove), object (optional absent objects stay absent until "Add"), object_list (rows with up/down/remove), json (applies only valid JSON). "reset" removes an explicit value. Empty optional values are removed, never sent.
* Generic fallback: any field without a known widget is rendered from its `kind` (tagged "generic"); data keys unknown to the schema appear under "Other fields in this spec" as editable JSON, so nothing is silently dropped.
* Validation: debounced (400 ms) `POST /api/specs/validate`, stale responses ignored; errors inline per field (list rows included), counts per section in the side nav, summary list whose items open collapsed panels and focus the field; warnings inline and in the summary; success card with spec hash, run ids, checkpoints and spend caps. Errors at a collapsed Advanced group open it.
* YAML tab: generated preview; "Edit as YAML" validates through the same endpoint (`{yaml}`), applies to the form as soon as it parses (so it round-trips), shows syntax errors without sending anything.
* Save: to drafts only; overwrite confirmation for an existing draft; 409 on a new name asks to overwrite; 422 shows the server errors in place; Ctrl/Cmd+S; examples are editable in memory and saved under a typed draft name. Sticky bar with status, unsaved-changes badge, Validate, Discard, Save, Launch.
* No data loss: `beforeunload` plus a capturing click listener that confirms before any in-app link while dirty (BrowserRouter has no blocker); unsaved edits are also kept in `sessionStorage` and restored with a "Discard them" banner (covers the back button).

### Review
* Overview of runs with counters and progress; queue per run (all items loaded, paged by 500).
* Filters (status pending/decided/confirmed/rejected/unsure/all, kind, group, detector) kept in the URL; counters and progress bar; cards with kind, group, detector, rule/judge tag, checkpoint and time, evidence (clamped, expandable), draft label and note, decision buttons with note, latest decision plus lazily loaded history (newest first).
* Keys: `j`/`k`, `c`/`r`/`u`, `n` (note), `Esc`; ignored while typing. After a decision the cursor moves on.
* Batch decide for the filtered set (button enabled only when a kind/group/detector filter narrows it), confirmation dialog with decision and note, chunks of 500.
* Append-only: a re-decision adds a record; the card shows the latest and `History (n)`.
* Transcript link: `/runs/<id>?tab=transcript&t_s=<seconds>&k=<checkpoint>` (the run-detail tab must read `t_s`/`k`; brief said `cursor`, tell me if the other agent chose a different name).

## Tests

* `npm test`: **123 passed** in 11 files (formLogic 13, specForm 25, SpecEditor 22, SpecsView 10, review 15, plus the existing 38). `npm run lint` and `tsc --noEmit` clean, `npm run build` OK.
* Real fixtures captured from `lrae ui`: `specs_schema.json`, `specs_list.json`, `spec_minidb_v3.json`, `specs_paths.json`, `validate_invalid.json`, and `review_queue.json` (25 items trimmed from the pilot's 123), `review_runs.json`.
* Covered: every widget type from the real schema, no field dropped, conditional visibility, required_if, error to field mapping (including list rows and collapsed groups), summary jump to field, generic fallback and unknown keys, round trip (untouched form sends exactly the server's data; one edit changes exactly one key), unsaved guard (confirm, beforeunload, session restore), save/overwrite/422, YAML round trip and syntax errors, list actions, review keyboard flow, batch, history, hostile strings (names, evidence, notes, messages stay text).
* `node scripts/smoke.mjs --runs-dir <scratch> --shots <dir> --decide --write-drafts --review-run <id>`: PASSED. New flags: `--decide` is refused unless `--runs-dir` is an explicit scratch dir; `--write-drafts` duplicates `pilot-scripted` into `spec/drafts/` and deletes it again (worktree's `spec/drafts` is empty afterwards). Review screenshots used a scratch runs dir holding only the pilot's `scorer.jsonl` and manifest; the real `runs/` was never touched.

## Screenshot notes (looked at them)
Specs list, editor (clean and with an error), YAML tab, review queue and decided view render well in light and dark and at 420 px. Fixed after looking: banner word breaking, review progress bar sliver at 0%, full-page review capture (now viewport-only). Known roughness: the editor page is long (one scroll); the same help sentence can appear as a field note and a validation warning.

## Deviations and open issues
* Back/forward browser buttons cannot be intercepted with `BrowserRouter`; covered by the session restore instead. Using a data router (`createBrowserRouter`) would allow `useBlocker`.
* Saved YAML loses comments (backend behaviour); "Duplicate to draft" keeps them.
* The queue loads everything (cap 5000 items); fine for 123.
* `/specs/_new` is the blank-spec route (names cannot start with `_`, so no clash).
* Backend wishes: validate could return the parsed `data` for YAML input (today the client parses with `yaml`); a server-side `group`/`name` filter on the queue would avoid loading everything for big runs.
* Shared-file edits: `routes.tsx`, `nav.ts`, `components/index.ts`, `api/index.ts`, `api/client.ts` (one-word change), `package.json`/lock (`yaml`). Expect trivial merge conflicts in those.
