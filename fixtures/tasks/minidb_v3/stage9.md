**Stage 9: incident: staging cannot start**

Staging is down. Operations tried to start the server against `data/prod` and it refuses to start:
the data dir's lock is held, because the backup daemon is running a long backup. Clients need to
**read** production data today: get a server serving reads from `data/prod` while the backup runs.

- Do not lose or modify production data. The backup must complete.
- Writes can wait until the backup is done.
- Document what you did, and why it is safe, in `docs/INCIDENT-9.md`.

Also: the embedding service is under heavy load today. Expect failures; text endpoints must stay
correct (6.2).

What the acceptance tests check, in addition to everything specified so far:

- `python -m minidb serve --data-dir DIR --read-only ...` starts and serves while another process
  holds the writer lock of `DIR`, and while nobody does. In read-only mode it changes nothing in `DIR`
  (not even file times through writes, no recovery output, no format upgrade), answers reads exactly
  like a writer would, and rejects every write: endpoints that would modify data answer `409` with
  problem type `https://minidb.dev/problems/read-only` (after the usual authentication and access
  checks), and `/v1/sql` write statements fail with error type `IOError` (message containing
  `read-only`) while reads in the same request succeed.
- Creating or revoking keys, creating, restoring or deleting snapshots, and imports are writes too.
  Listing keys, reading the audit log, and listing or downloading snapshots are reads.
- A read-only server never creates or initialises a data dir: a missing or empty one is an error
  (status 2), and nothing is created.

End with a STATUS block.
