"""Payload columns: the values at one payload path for every slot, as numpy arrays, so filters are
evaluated a whole collection at a time (``filters.Filter.mask``).

A column is built the first time a filter uses its path and is then kept up to date as points are
added (at most ``MAX_COLUMNS`` per collection, least recently used dropped). A slot holding exactly
one scalar at the path is stored in the array of its type: ``nums`` (float64, NaN elsewhere; integers
beyond 2**53 excepted), ``strs`` (codes into ``codes``, -1 elsewhere) or ``bools`` (0/1, -1 elsewhere).
Any other slot that has values there (several values, arrays, objects, huge integers) is kept in
``multi`` and tested value by value. Dead slots keep stale entries; callers mask them out.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

import numpy as np

from minidb.collection.filters import _values
from minidb.collection.points import is_number

MAX_COLUMNS = 32
EXACT_INT = 2 ** 53


class Column:
    def __init__(self) -> None:
        self.n = 0
        self.cap = 0
        self.nums = np.zeros(0, np.float64)
        self.strs = np.zeros(0, np.int32)
        self.bools = np.zeros(0, np.int8)
        self.codes: dict[str, int] = {}
        self.multi: dict[int, list] = {}

    def _grow(self, need: int) -> None:
        if need <= self.cap:
            return
        cap = max(need, 2 * self.cap, 1024)
        nums = np.full(cap, np.nan)
        nums[: self.n] = self.nums[: self.n]
        strs = np.full(cap, -1, np.int32)
        strs[: self.n] = self.strs[: self.n]
        bools = np.full(cap, -1, np.int8)
        bools[: self.n] = self.bools[: self.n]
        self.nums, self.strs, self.bools, self.cap = nums, strs, bools, cap

    def extend(self, start: int, payloads: list, path: tuple) -> None:
        """Values of ``payloads`` for the slots ``start``, ``start + 1``, ..."""
        end = start + len(payloads)
        self._grow(end)
        self.nums[start:end] = np.nan
        self.strs[start:end] = -1
        self.bools[start:end] = -1
        for slot in range(start, end):
            self.multi.pop(slot, None)
        for i, payload in enumerate(payloads):
            if payload is None:
                continue
            values = _values(payload, path)
            if not values:
                continue
            slot = start + i
            v = values[0]
            if len(values) == 1:
                if isinstance(v, bool):
                    self.bools[slot] = int(v)
                    continue
                if isinstance(v, str):
                    self.strs[slot] = self.codes.setdefault(v, len(self.codes))
                    continue
                if is_number(v) and (isinstance(v, float) or -EXACT_INT <= v <= EXACT_INT):
                    self.nums[slot] = v
                    continue
            self.multi[slot] = values
        self.n = max(self.n, end)


class PayloadColumns:
    """The column cache of one collection (``payloads`` is the collection's slot list)."""

    def __init__(self) -> None:
        self.cols: OrderedDict[tuple, Column] = OrderedDict()
        self.lock = threading.Lock()         # readers share a collection; they may build columns

    def column(self, path: tuple, payloads: list, n: int) -> Column:
        with self.lock:
            return self._column(path, payloads, n)

    def _column(self, path: tuple, payloads: list, n: int) -> Column:
        col = self.cols.get(path)
        if col is None:
            col = Column()
            col.extend(0, payloads[:n], path)
            col.n = n
            self.cols[path] = col
            while len(self.cols) > MAX_COLUMNS:
                self.cols.popitem(last=False)
        else:
            self.cols.move_to_end(path)
            if col.n < n:
                col.extend(col.n, payloads[col.n:n], path)
        return col

    def added(self, start: int, payloads: list) -> None:
        with self.lock:
            for path, col in self.cols.items():
                col.extend(start, payloads, path)

    def clear(self) -> None:
        with self.lock:
            self.cols.clear()


class View:
    """What ``Filter.mask`` sees of a collection: ``n`` slots, columns by path, slots of ids."""

    def __init__(self, coll: Any) -> None:
        self.coll = coll
        self.n = coll.n_slots

    def column(self, path: tuple) -> Column:
        return self.coll.columns.column(path, self.coll.payloads, self.n)

    def id_slots(self, ids) -> np.ndarray:
        slot_of = self.coll.slot_of
        return np.array([slot_of[i] for i in ids if i in slot_of], np.int64)
