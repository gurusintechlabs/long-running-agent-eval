"""limit/offset helpers shared by list endpoints."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


def clamp_page(
    limit: int | None,
    offset: int | None,
    default_limit: int = 20,
    max_limit: int = 100,
) -> PageParams:
    """Normalise user-supplied limit/offset into safe values.

    Missing limit -> default_limit; limit is clamped to [1, max_limit];
    offset is clamped to >= 0.
    """
    if limit is None:
        limit = default_limit
    limit = max(1, min(int(limit), max_limit))
    offset = max(0, int(offset or 0))
    return PageParams(limit=limit, offset=offset)


def has_more(total: int, params: PageParams) -> bool:
    """True when another page exists after the one described by params."""
    return params.offset + params.limit < total
