"""Entry point: ``python -m minidb [--db PATH]`` reads SQL from stdin and writes JSON lines to stdout.

Without ``--db`` the database lives in memory for the life of the process; with ``--db PATH`` it
is kept durably in ``PATH`` (see ``minidb.durable``). ``minidb.protocol`` constructs ``Engine()``
without arguments, so the path is handed over through ``Engine.db_path``.
"""
import sys

from minidb.engine import Engine
from minidb.protocol import main

args = sys.argv[1:]
if len(args) == 2 and args[0] == "--db":
    Engine.db_path = args[1]
elif args:
    print("usage: python -m minidb [--db PATH]", file=sys.stderr)
    raise SystemExit(2)

raise SystemExit(main())
