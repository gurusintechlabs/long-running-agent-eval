"""Entry points.

* ``python -m minidb [--db PATH]`` reads SQL from stdin and writes JSON lines to stdout. Without
  ``--db`` the database lives in memory for the life of the process; with ``--db PATH`` it is kept
  durably in ``PATH`` (see ``minidb.durable``). ``minidb.protocol`` constructs ``Engine()`` without
  arguments, so the path is handed over through ``Engine.db_path``.
* ``python -m minidb serve --data-dir DIR --port N [--read-only]`` runs the HTTP server
  (``minidb.server.app``).
"""
import sys

args = sys.argv[1:]
if args and args[0] == "serve":
    from minidb.server.app import main as serve
    raise SystemExit(serve(args[1:]))

from minidb.engine import Engine  # noqa: E402
from minidb.protocol import main  # noqa: E402

if len(args) == 2 and args[0] == "--db":
    Engine.db_path = args[1]
elif args:
    print("usage: python -m minidb [--db PATH] | python -m minidb serve --data-dir DIR --port N", file=sys.stderr)
    raise SystemExit(2)

raise SystemExit(main())
