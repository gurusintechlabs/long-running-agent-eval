"""The mutation journal.

Every change to the catalog (``minidb.catalog``) records two things here: how to undo it, and a
logical *redo* operation (a JSON-serializable list) describing it. The journal serves three
purposes:

* transactions: ROLLBACK undoes every entry since BEGIN, COMMIT forgets them;
* statement atomicity: a statement that fails part-way is undone from its own mark;
* durability: the redo operations of a statement (or of a committed transaction) are what the
  storage layer writes to its log and replays after a restart.

Costs are proportional to what was changed, never to the size of the database.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

Undo = Callable[[], None]


class Journal:
    def __init__(self) -> None:
        self._entries: list[tuple[Undo, Optional[list]]] = []
        self.enabled = True

    def record(self, undo: Undo, redo: Optional[list]) -> None:
        if self.enabled:
            self._entries.append((undo, redo))

    def mark(self) -> int:
        return len(self._entries)

    def undo_to(self, mark: int) -> None:
        """Undo every entry recorded after ``mark``, newest first."""
        entries = self._entries
        while len(entries) > mark:
            undo, _ = entries.pop()
            undo()

    def redo_since(self, mark: int) -> list[Any]:
        return [redo for _, redo in self._entries[mark:] if redo is not None]

    def clear(self) -> None:
        self._entries.clear()
