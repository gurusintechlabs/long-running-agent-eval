"""Entry point: ``python -m minidb [--db PATH]`` reads SQL from stdin and writes JSON lines to
stdout. With ``--db PATH`` the database is kept in the file ``PATH``; without it, in memory."""
import argparse
import sys
from typing import Any

from minidb import protocol


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="python -m minidb")
    parser.add_argument("--db", metavar="PATH", help="database file (default: in memory)")
    args = parser.parse_args(argv)
    if args.db is None:
        return protocol.main()
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    try:
        from minidb.engine import Engine
        engine: Any = Engine(args.db)
    except Exception as exc:  # noqa: BLE001 - report per statement instead of dying silently
        engine = protocol._BrokenEngine(exc)
    protocol.serve(sys.stdin, sys.stdout, engine)
    close = getattr(engine, "close", None)
    if close is not None:
        close()  # an open transaction is rolled back (it was never logged anyway)
    return 0


raise SystemExit(main(sys.argv[1:]))
