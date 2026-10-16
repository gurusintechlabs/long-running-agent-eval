"""slugify_lite: tiny vendored slug generator (ASCII, dash separated).

Vendored copy; treat as read-only.
"""
from __future__ import annotations

import re
import unicodedata

__all__ = ["slugify", "__version__"]
__version__ = "1.2.0"  # patched locally

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_length: int = 80, separator: str = "-") -> str:
    """Convert ``text`` into a lowercase ASCII slug.

    >>> slugify("Hello, World!")
    'hello-world'
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _NON_ALNUM.sub(separator, ascii_text).strip(separator)
    if max_length and len(slug) > max_length:
        slug = slug[:max_length].rstrip(separator)
    return slug
