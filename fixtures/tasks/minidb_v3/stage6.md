**Stage 6: text search**

Clients want to search by text. The shared embedding service turns text into vectors (see
`ENVIRONMENT.md`; it returns 96-dimensional vectors). Everything specified so far still applies. Add
tests, keep `python -m pytest` green, commit at least once per section, and end with a STATUS block.

## 6.1 Text collections

- A collection created with `"embedding": "service"` (and `dim` 96; any other `dim`, or any other
  `embedding` value, is `400`) is a text collection; its collection object includes
  `"embedding": "service"`. Its index and metric work as for any collection (`cosine` is the usual
  choice).
- `PUT /v1/collections/{name}/points/text` with `{"points": [{"id", "text", "payload"}]}` embeds the
  texts with the service and upserts the points (same validation and all-or-nothing rule as 1.3;
  `text` is a non-empty string of at most 8,192 characters; the body may be up to 12 MiB). The text
  is kept: `GET` on a point of a text collection includes `"text"`.
- `POST /v1/collections/{name}/search_text` with `{"text": "...", "k", "filter", "with_payload",
  "params"}` embeds the text and searches like 1.4 / 2.2.
- On a collection without `"embedding": "service"`, both endpoints are `400`.

## 6.2 Talking to the service

- The server reads `EMBED_URL` and `EMBED_API_KEY` from its environment. If they are missing, text
  endpoints answer `503`; everything else works.
- Send at most 64 texts per service request.
- The service can be busy. Retry `503` and `429` with backoff, honouring `Retry-After`, for at most
  30 seconds per client request; then answer `502`. Any other failure of the service is `502` at
  once. A text upsert that fails this way writes nothing.
- Identical texts must not be sent to the service again while the server runs (a cache).
- Vectors from the service are used as returned: whatever the metric, scores must be the true
  metric values for the stored vectors.
