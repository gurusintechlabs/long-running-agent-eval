"""Entry point: ``python -m minidb`` reads SQL from stdin and writes JSON lines to stdout."""
from minidb.protocol import main

raise SystemExit(main())
