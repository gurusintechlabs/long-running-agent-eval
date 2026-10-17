"""Names (CR-4): identifiers keep their spelling but are matched case-insensitively.

``Ident`` is a ``str`` holding the spelling a name was given; it compares and hashes like its
lower-case form, so dicts, sets and lists of names match ``users``, ``USERS`` and ``Users``
alike. (A ``str`` subclass that overrides ``__eq__`` is consulted first even when it is the
right-hand operand, so ``'users' == Ident('Users')`` holds too.) Every name that enters the
catalog must be an ``Ident``: a plain ``str`` key with capitals would hash differently.
"""
from __future__ import annotations

from typing import Any


class Ident(str):
    __slots__ = ()

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, str) and self.lower() == other.lower()

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self.lower())
