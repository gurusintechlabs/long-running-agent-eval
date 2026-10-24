# UI API: compare, survival and reports (phase U7)

Route modules: `ui_server/routes/compare.py`, `ui_server/routes/reports.py`. All endpoints need the `X-LRAE-Token` header; the host/origin guard of `app.py` applies to all of them (so a POST with a foreign `Origin` is 403). Cost is always "estimated (API-equivalent)", never a bill.

## GET /api/compare?runs=a,b,c
`runs`: 1 to 8 comma-separated run ids (duplicates dropped; malformed id -> 400; unknown or symlink-escaping id -> 404; more than 8 -> 400).

Response:
- `run_ids`, `base` (the first id; deltas are against it), `metrics` (core P R D C W X S first, then alphabetical).
- `runs[]`: `run_id`, `summary` (same shape as `/api/runs`), `ingested`, `checkpoints[{k,t_s}]` (from the orchestrator log, always present), `series{metric:{k[],t_s[],value[]}}` (so both x axes are available), `counters{cum_cost_usd,cost_usd,context_fill_max,compactions: same shape}`, `hazards[]`. A non-ingested run has `ingested:false` and empty `series`, `counters`, `hazards`.
- `aligned_by_k{metric:{k[], values{run_id:[v|null]|null}}}`: union of checkpoints, `null` where a run has none.
- `metric_deltas[]`: per metric `final`, `mean`, `min`, `max`, `delta_vs_base` per run. `summary_deltas[]`: `duration_s, ttfh_s, cost_usd, tokens, hazard_count, checkpoints`.
- `not_ingested[]`, `notes[]` (a sentence per non-ingested run), `cost_note`.
NaN and infinities are returned as `null`. Paths are scrubbed like the other run endpoints.

## GET /api/survival?experiment=&config=&dimension=
`experiment` required (id allowlist, else 400). `config`: optional comma list filter. `dimension`: optional, an event is then a hazard of that dimension only (as `survival_inputs`). 404 when there is no store or the experiment is not in it.

Calls `analysis.survival.survival_inputs`, `summarize`, `headline_text` (nothing is reimplemented). Per group (task class, config): `n`, `events`, `censored`, `censored_by_reason`, `km{times,surv,lower,upper,n_risk,n_event,censor_times,censor_surv}` (seconds; the UI prepends (0, 1)), `median_s`, `median_text`, `median_ci_boot_s[lo,hi]` (seeded bootstrap, as in the dashboard), `headline_s`, `headline_text` (D-11, target 0.8, level 0.90), `headline_available`. If a group cannot be computed it carries `available:false`, `headline_text:"not available"` and the error. Top level also has `excluded{reason:count}` (FAILED/unfinished runs, not in the survival set), `runs_total`, `target`, `level`, `note`.

## GET /api/reports
`experiments[]` (union of experiments in the store and folders under `runs/reports/`): `experiment_id`, `in_store`, `has_reports`, `dashboard`/`pdf` (`{name,bytes,mtime}` or null), `figures[]`, `built_epoch`, `older_than_store`. Also `ingest` (the `/api/ingest/status` object), `chrome{available,error}` and `cost_note`. Symlinked folders or files are not listed.

## GET /api/reports/{experiment}/file?name=
Only `dashboard.html`, `report.pdf` and `figures/<name>.png` (`[A-Za-z0-9][A-Za-z0-9._-]*`) are served; anything else is 404. The experiment id uses the run-id allowlist; the file must be a regular file, not a symlink, resolved inside `runs/reports/<experiment>`. Types: `text/html; charset=utf-8`, `application/pdf` (`Content-Disposition: inline`), `image/png`. HTML gets `Content-Security-Policy: sandbox; default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'`: no scripts, opaque origin, so it cannot call the API or read the token. (`app.py` stamps its own CSP on every response, so an outermost ASGI wrapper in `reports.py` swaps it for this one on the HTML file route only.)

Because `<img>`/`<iframe src>` cannot send the token header, the UI fetches the HTML and the listed figures with the header, inlines the figures as `data:` URLs and shows the result in `<iframe sandbox="" srcdoc>`; the PDF opens as a blob in a new tab.

## POST /api/reports/{experiment}/rebuild
Body `{kind: "dashboard"|"pdf", allow_stale?: bool}`. Runs `python -m runner.cli dashboard <exp> --db <store> --out <runs>/reports/<exp>` or `... report <exp> --pdf --db ... --out ...` (the same CLI verbs as `lrae dashboard` / `lrae report --pdf`; `--db/--out` are passed explicitly because the server's runs dir may not be `./runs`). cwd is the repo root.
- Env (UI-7): `PATH, LANG, LC_ALL, TMPDIR` and `LRAE_CHROME` (so an operator's Chrome override reaches `find_chrome`), plus `MPLCONFIGDIR` under `TMPDIR`. No `HOME`: the report code only reads `metrics.sqlite` and Chrome runs with a throwaway `--user-data-dir`; the end-to-end PDF test passes without it.
- Single flight: a second request while one runs gets 409 `{code:"busy"}`.
- Refusals: 404 `not_in_store` (experiment not ingested), 409 `store_stale` (re-ingest first, or send `allow_stale:true`), 424 `chrome_not_found` (pdf only, message from `find_chrome`), 422 bad kind, 404 bad id. Errors carry `detail:{code,message}`.
- Result `{ok, kind, exit_code, output (last 4000 chars, paths scrubbed), artifact, duration_s, stale_store}`; HTTP 500 with the same body when the CLI fails or times out (420 s).
