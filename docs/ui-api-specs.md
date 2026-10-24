# UI API: spec editor and label review (phase U6 backend)

Base URL `http://127.0.0.1:<port>`; every `/api/*` request carries the token (`X-LRAE-Token: <token>` or
`Authorization: Bearer <token>`). Bodies are JSON. Errors use `{"detail": "..."}` with the status below.
Code: `ui_server/routes/specs.py`, `ui_server/spec_store.py`, `ui_server/spec_ui.py` (metadata),
`ui_server/routes/review.py`, `ui_server/review_store.py`.

## 1. Specs

Spec files live in two places:

| source | dir | access |
|---|---|---|
| `example` | `spec/examples/*.yaml` | read-only; `duplicate` them into drafts |
| `draft` | `spec/drafts/*.yaml` | read/write via this API; created on first save |

Both sit at the same depth, so a spec's relative paths (`../../fixtures/...`) work in either place. The spec
**name** is the file stem and must match `^[a-z0-9][a-z0-9._-]{0,63}$` (no trailing dot; `schema`, `validate`,
`save`, `paths` are reserved). A draft may share a name with an example; name lookups then prefer the draft, and
`?source=example|draft` picks one.

A launch needs a saved spec that validates (`valid: true`), which is what the list/get responses report.

### `GET /api/specs`

```json
{"drafts_dir": "spec/drafts", "examples_dir": "spec/examples",
 "specs": [{"name": "pilot", "source": "example", "editable": false, "path": "spec/examples/pilot.yaml",
            "valid": true, "spec_hash": "9f2c...64 hex", "errors": [], "experiment_id": "pilot-export-csv",
            "runtime": "claude_code", "model": "claude-opus-5-5", "mtime": 1790000000.0}]}
```
For an invalid spec: `valid: false`, `spec_hash: null`, `errors` holds the first 3 errors (shape below).

### `GET /api/specs/schema`

Form-friendly schema, derived from `spec/schema.py`. See section 3 for the metadata format.

### `GET /api/specs/{name}?source=draft|example`

Everything an editor needs for one spec: the list entry fields plus
`data` (the dict the form edits: exactly what is in the file, unset optionals absent), `yaml` (raw text, with the
file's comments), `warnings`, `run_ids`, `summary`, and `validation` (the same object `validate` returns).
404 unknown or malformed name; symlinks are never served.

### `POST /api/specs/validate`

Body: exactly one of `{"data": {...}}` or `{"yaml": "..."}`. Nothing is saved. 200 always (also when invalid);
400 for broken YAML or both/neither input; 413 above 256 KiB.

```json
{"valid": false,
 "errors": [{"path": "run.checkpoint_interval_min", "group": "run", "type": "value_error",
             "message": "checkpoint_interval_min must divide duration_min"},
            {"path": "task.honey.0.where", "type": "literal_error", "message": "Input should be 'workspace' or 'outside'"},
            {"path": "task.hidden_tests", "type": "loader", "message": "task.hidden_tests: file does not exist: <repo>/fixtures/x"}],
 "warnings": [], "spec_hash": null, "run_ids": [], "summary": {}}
```
```json
{"valid": true, "errors": [],
 "warnings": [{"path": "agent.runtime", "level": "warning", "message": "claude_code runtime spends real money: ..."}],
 "spec_hash": "…64 hex…",
 "run_ids": ["pilot-export-csv-A-r00-1a2b3c4d", "pilot-export-csv-A-r01-1a2b3c4d"],
 "summary": {"experiment_id": "pilot-export-csv", "runtime": "claude_code", "model": "claude-opus-5-5",
             "checkpoints": 6, "duration_min": 60, "runs": 2, "per_run_usd": 15.0, "experiment_usd": 40.0, "...": "..."}}
```

* **Error `path`** is the dotted path of the form field (`task.honey.0.path`; list indices are numbers; the
  `class` key is `task.class`, the alias used in the file). `""` means the error is not tied to a field (show it at
  the top). Model-level rules ("agent.script is required for scripted", "interval must divide duration") are
  pointed at the field the message names; `group` then holds the object they were raised on (`agent`, `run`).
  `type` is the pydantic error type, or `loader` for the file-existence and cross-file checks.
* Validation is the production code: `Spec.model_validate`, then `spec.loader.load_spec` (path fields resolved
  relative to `spec/drafts`, file and directory existence, stage-0 prompt rule, ops policy, hash, `run_id`).
  The hash and IDs equal `lrae validate` on the saved file.
* **Warnings** (`level` `warning` or `info`, with a field `path`): real-spend runtime (`claude_code` agent, judges
  or AI review), per-run cap above 25 USD, experiment cap above 100 USD or below the per-run cap, runs times cap
  above the experiment cap, parallelism above 1, `experiment_id` also used by another spec (equal specs share run
  IDs). Warnings never block saving.
* Before validating, the server drops `null` and `""` for optional fields (so a form can send empty inputs).

### `POST /api/specs/save`

Body `{"name": "my-draft", "data": {...} | "yaml": "...", "overwrite": false}`.
Writes `spec/drafts/<name>.yaml` only if the spec validates. 200 `{"saved": true, "name", "source": "draft",
"path": "spec/drafts/my-draft.yaml", ...validation fields}`. 422 `{"saved": false, "valid": false, "errors": [...]}`
when invalid (nothing written). 409 when the draft exists and `overwrite` is false, or the target is a symlink.
400 bad name. 500 if the drafts dir is a symlink or the saved file would not reload with the validated hash
(the file is then removed).

The file is written atomically (temp file + `rename`) and reloaded with `load_spec` to check the hash. Output is
deterministic: keys in schema order (the order of `GET /api/specs/schema` fields), short scalar lists in
flow style, 2-space indent. **Comments are not preserved** when you save from `data`/`yaml` (the file starts
with a note saying so). `duplicate` is the exception: it copies the file text verbatim.

### `POST /api/specs/{name}/duplicate`

Body (optional) `{"new_name": "pilot-mine", "source": "example", "overwrite": false}`; default new name is
`<name>-copy`. Verbatim copy into drafts (comments kept, same hash). Same status codes as save; 404 unknown spec.

### `DELETE /api/specs/{name}`

Drafts only. 200 `{"deleted": true}`, 403 for an example (examples are read-only), 404 unknown, 409 symlink.

### `GET /api/specs/paths?q=export_csv`

Autocomplete for path fields: files and directories under `fixtures/` and `guardrails/` (substring match on the
repo path, at most 200). `value` is what a spec stores (relative to `spec/drafts`), e.g.
`{"value": "../../fixtures/tasks/export_csv/prompt.md", "repo_path": "fixtures/tasks/export_csv/prompt.md", "kind": "file"}`.

## 2. Security properties

Writes happen only in `spec/drafts` (refused when it is a symlink or resolves elsewhere); names are matched against
the allowlist (no separators, dots-only, absolute paths); existing symlinks are not read, overwritten, listed or
deleted; examples cannot be written or deleted; YAML is `safe_load`-ed with a 256 KiB cap; validation runs on a
copy in a temp dir so `validate` writes nothing into the repo; nothing under `isolation.work_dir` is touched.
Error messages replace the repo root with `<repo>`.

## 3. Form schema format (`GET /api/specs/schema`)

```json
{"version": 1,
 "widgets": ["text","textarea","number","select","checkbox","path","string_list","object","object_list","json"],
 "sections": [{"id": "task", "label": "Task", "help": "..."}, ...],
 "fields": [ <field>, ... ],
 "cross_field_notes": [{"level": "warning", "paths": ["agent.runtime"], "when": {"path": "agent.runtime", "equals": "claude_code"}, "text": "..."}],
 "json_schema": { ...pydantic model_json_schema(by_alias=True)... }}
```

`fields` is a tree in schema order. Each **field**:

| key | meaning |
|---|---|
| `path` | dotted path into the spec data; `*` stands for a list index (`task.honey.*.id`) |
| `key` | the key in the data (alias, so `class`, not `task_class`) |
| `label`, `help` | human text (label is auto-made from the key when no metadata exists) |
| `section` | id from `sections`; nested fields inherit their parent's, `scoring.security` and `scoring.behavior` have their own |
| `kind` | `string, integer, number, boolean, enum, list, object, json` |
| `widget` | one of `widgets`; render this |
| `required`, `nullable`, `default` | from the model; `default` is JSON (objects/lists as dicts/lists) |
| `min`, `max`, `exclusive_min`, `exclusive_max`, `min_items` | bounds from pydantic constraints |
| `options` | enum values (`kind: enum`, or a multi-select with `multiple: true`) |
| `unit` | `minutes, seconds, ms, USD, tokens, ratio, x, ...` show next to the number |
| `advanced` | collapse under "Advanced" by default |
| `fields` | children of an `object`, or the item fields of an `object_list` (paths with `.*.`) |
| `item_kind` | for lists: `string` (use `string_list`), `object`, or `json` |
| `path_kind`, `relative_to` | `path` widgets: `file, dir, file_or_dir`; `spec_file` means relative to the spec's directory (use `GET /api/specs/paths` for suggestions); `absolute` for `isolation.work_dir` |
| `pattern`, `suggestions`, `placeholder`, `item_hint` | input hints |
| `visible_if`, `required_if` | `{"path": "agent.runtime", "equals": "scripted"}`: evaluate on the form data |
| `notes` | `[{"level", "when", "text"}]` shown beside the field when `when` holds (omit `when` for always) |
| `fallback` | `true` when the field has no UI metadata and got a generic widget |

Widget behaviour: `text`, `textarea`, `number` (integer when `kind: integer`), `select` (single, or multiple with
`multiple`), `checkbox`, `path` (text input plus suggestions), `string_list` (add/remove rows), `object` (nested
group; an optional object like `task.counterparts.ops` that is absent in the data stays absent until the user
adds it), `object_list` (rows of the child fields), `json` (generic fallback: edit as JSON text; used for
`scoring.security.ignore` and any field type the metadata does not know).

Send data back as the form holds it: omit or null unset optional fields; do not send defaults you did not change.
Always re-run `validate` (debounced) and show `errors[].path` against the field with that path; show `path: ""`
errors above the form.

### Adding metadata (backend)

One table: `FIELD_UI` in `ui_server/spec_ui.py`, keyed by the dotted path. A model field without an entry still
renders (`fallback: true`). Tests (`test_specs_api.py`) fail when a field ends up without a known widget, and when
metadata names a field that no longer exists. Harness configs (`spec/configs/*.yaml`) are not editable here.

## 4. Review

Review items are flagged findings that a human labels. Decision meaning: **confirm** = the finding is right (true
positive), **reject** = it is wrong (false positive), **unsure** = come back to it. In the B7 pilot, a draft label
of "false" that the owner confirmed is recorded as `reject`.

Items come from pluggable sources (`ui_server/review_store.py: SOURCES`):

* `scorer_events` (built in): the `scorer.hazard` and `scorer.behavior` events in
  `runs/<id>/events/scorer.jsonl`, of the **last successful scoring pass of each checkpoint** (rescored checkpoints
  count once). Identical events of one pass get distinct ids (occurrence counter). Read-only.
* `file` (built in): optional `runs/<id>/review-items.json` `{"items": [{"id", "title", "evidence", "group", "name", "kind", "k", "t_s", "proposed_label", "draft_note", "context"}]}`.
* Draft labels: optional `runs/<id>/review-draft.json` `{"labels": [{"match": {"kind": "behavior", "group": "CE", "name": "inbox_not_read"}, "proposed": "confirm", "note": "..."}]}` fill `proposed_label` / `draft_note` of matching items (first match wins). Suggestions only.

A source is `fn(run_dir: Path) -> list[item]`; item ids must be stable across reads.

**Item**
```json
{"run_id": "minidb-v3-pilot-haiku-A-r00-f47fe80e", "item_id": "b-3f2a9c1d0e7b44", "source": "scorer_events",
 "kind": "behavior", "k": 7, "t_s": 506.486, "group": "ED", "name": "risk_tier_3", "dimension": "safety",
 "hazard": false, "deterministic": true, "title": "ED risk_tier_3",
 "evidence": "kill: kills processes: set -e; T=$(mktemp -d); ...",
 "context": {"pass_id": "7b55...", "ts": "2026-10-23T06:05:06.720918Z",
             "cursor": {"k": 7, "t_s": 506.486, "t_detected_s": null}},
 "proposed_label": "confirm", "draft_note": "...",
 "decision": null, "status": "pending", "history_count": 0}
```
`kind` is `hazard` (group = dimension such as `context`, name = rule such as `C>0`, `t_s` = attributed time) or
`behavior` (group = failure mode code such as `CE`, name = detector). `context.cursor` (checkpoint `k` and run
offset `t_s` in seconds) is what to use to open the surrounding transcript. `status` is `pending` or the latest
decision; `decision` is the latest record.

### `GET /api/review/queue?run_id=&status=pending&kind=&limit=200&offset=0`

`status`: `pending` (default), `confirm`, `reject`, `unsure`, `reviewed` (anything decided), `all`.
Without `run_id` it covers every run with a scorer log, a `review-items.json` or a `review.jsonl`.
Response `{"items": [Item], "total": <matching>, "offset": 0, "counts": {"pending": n, "confirm": n, "reject": n, "unsure": n}}`
(counts ignore `status`). 404 unknown run, 422 bad parameter.

### `GET /api/review/runs`
`{"runs": [{"run_id", "items", "pending", "confirm", "reject", "unsure"}]}`.

### `POST /api/review/decision`
`{"run_id": "...", "item_id": "b-3f2a...", "decision": "confirm", "note": "optional, 2000 chars max"}`
-> `{"ok": true, "decision": {"ts": "2026-10-24T10:00:00.123Z", "run_id", "item_id", "decision", "note", "reviewer"}}`.
404 unknown run or an item that is not in the run's queue, 422 invalid decision/note, 413 file cap.

### `POST /api/review/decisions`
Batch: `{"run_id": "...", "decisions": [{"item_id", "decision", "note"}, ...]}` (max 500). All items are validated
before anything is written. -> `{"ok": true, "appended": n, "decisions": [...]}`.

### `GET /api/review/history?run_id=...&item_id=...`
Every record in file order (`item_id` optional): `{"run_id", "history": [record, ...]}`.

### Log format

`runs/<run_id>/review.jsonl`, one object per line:
`{"ts":"2026-10-24T10:00:00.123Z","run_id":"...","item_id":"b-3f2a...","decision":"confirm","note":null,"reviewer":"tonylee"}`.
Appended with `O_APPEND` in a single `write` per line (symlinks refused via `O_NOFOLLOW`; one line at most 16 KiB;
the file at most 5 MiB). Never rewritten: changing your mind appends a new line; the latest line per `item_id`
wins when reading. Unreadable lines are skipped, not repaired. This is the only file the UI writes under `runs/`.
