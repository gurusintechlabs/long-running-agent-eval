"""The stable multi-key sort shared by ORDER BY (queries, set operations) and window
functions (section 3, CR-1)."""
from __future__ import annotations

from typing import Any, Callable

from minidb import values as v
from minidb.protocol import SQLTypeError

# A sort key: (getter of the key from an entry, descending, NULLs first)
SortKey = tuple[Callable[[Any], Any], bool, bool]


def sort_entries(entries: list, keys: list[SortKey]) -> list:
    """Stable multi-key sort, NULLs placed first or last per key. Two non-NULL values of
    incomparable types under one key are a TypeError, whatever the sort would compare."""
    if not keys or len(entries) < 2:
        return entries
    for get, _, _ in keys:
        classes = {v.value_class(x) for x in map(get, entries) if x is not None}
        if len(classes) > 1:
            raise SQLTypeError("ORDER BY compares values of incomparable types: "
                               + ", ".join(sorted(classes)))
    entries = list(entries)
    for get, desc, nulls_first in reversed(keys):
        # NULL's key must be "larger" in the sort's own direction when it goes at the end of
        # an ascending sort or the start of a descending one.
        null_key = (1,) if nulls_first == desc else (-1,)
        entries.sort(key=lambda e, get=get, null_key=null_key: _sort_key(get(e), null_key),
                     reverse=desc)
    return entries


def _sort_key(x: Any, null_key: tuple) -> tuple:
    return null_key if x is None else (0, x)


def row_key(row: tuple) -> tuple:
    """Hashable key of a row: equal exactly for rows that are duplicates (DISTINCT)."""
    return tuple(v.value_key(x) for x in row)
