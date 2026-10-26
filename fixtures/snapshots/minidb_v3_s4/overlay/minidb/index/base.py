"""What every index structure shares: the search result and the metric's vector transform.

An index works on transformed vectors (unit length for ``cosine``, as given otherwise) and an index
distance (squared L2, or the negated inner product for ``dot``). It returns candidate slots; the
collection scores them exactly in the metric's own terms.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Hits:
    slots: np.ndarray            # candidates for the collection to score exactly
    exact: int                   # points scored exactly (``explain.candidates``)
    info: dict = field(default_factory=dict)     # extra explain fields


def transform(x: np.ndarray, metric: str) -> np.ndarray:
    x = np.asarray(x, np.float32)
    if metric == "cosine":
        norms = np.linalg.norm(x, axis=-1, keepdims=True)
        x = x / np.where(norms == 0, 1, norms)
    return x.astype(np.float32)
