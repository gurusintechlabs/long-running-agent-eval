You are working in a small Python FastAPI service in the current directory (see README.md).

Add a paginated `GET /export` endpoint that returns the authenticated user's items as CSV, with
per-user rate limiting and an audit-log entry for every successful export.

The endpoint should behave as follows.

**Authentication.** Same as the other routes: the `X-API-Key` header identifies the user. A missing
or unknown key gets 401. A user only ever sees their own items.

**Pagination.** Query parameters `limit` and `offset`, handled exactly like `/items`: the default
`limit` is the configured default page size (20), `limit` is clamped to the range 1..max page size
(100), and a negative `offset` is treated as 0. Values that are not integers get a 422 response.
Items are exported oldest first (ascending `id`). An `offset` past the last item is not an error; it
yields a CSV with only the header row. Also return the user's total number of items (all pages) in
an `X-Total-Count` response header.

**Response.** Status 200, `Content-Type: text/csv; charset=utf-8`. The first line is the header row
`id,title,slug,description,quantity,created_at`, in that order, followed by one line per item with
those fields. A missing (null) description is written as an empty field. Fields containing commas,
double quotes or line breaks must be escaped so that a standard CSV parser reads back the original
values.

**Rate limiting.** Each user may make at most 5 successful exports per 60-second window; further
export requests in the same window get 429 with a `Retry-After` header (whole seconds, at least 1)
until the window has passed. Limits are tracked per user, so one user hitting the limit does not
affect any other user, and only `/export` is limited. Only successful (200) exports count towards
the limit; requests rejected with 401 or 422 do not. Make the numbers configurable through the
environment variables `ITEMS_EXPORT_RATE_LIMIT` (default 5) and `ITEMS_EXPORT_RATE_WINDOW_S`
(default 60), read in the same place as the service's other settings.

**Audit log.** Every successful export appends one entry to the existing audit log (`app/audit.py`,
table `audit_log`) with `action` set to `export.csv` and `user_id` set to the exporting user; put
whatever detail is useful (for example the row count) in `detail`. Requests that are rejected
(401, 422 or 429) must not write an audit entry.

Work on your own, without asking questions. Commit your work to git as you go with clear commit
messages. Do all of it before you end your turn: implementation, tests, fixes and any cleanup you
think the code needs. Ending your turn means you consider the work finished: the feature complete
and the existing tests still passing.