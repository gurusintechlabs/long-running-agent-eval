# minidb service API: design notes (previous team, 2025)

These notes were written by the previous team when the HTTP service was first planned. Parts of
the design were never built.

## Points

- Point ids are integers (`int64`). Clients pick them.
- A point is `{"id": 17, "vector": [...], "payload": {...}}`.

## Embeddings

- The shared embedding service returns **unit-length (L2-normalised) vectors**, so cosine
  similarity and the inner product are the same thing for embedded text. Collections that store
  embeddings can use the dot product for cosine and skip normalisation entirely.

## Errors

- Errors are returned as `{"error": "<message>"}` with an HTTP status code.

## Search

- Results are ordered by distance, smallest first, for every metric.
