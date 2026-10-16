"""Runtime configuration, read from environment variables with safe defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Demo keys; real deployments override via ITEMS_API_KEYS="key1:1,key2:2".
DEFAULT_API_KEYS: dict[str, int] = {
    "key-alice": 1,
    "key-bob": 2,
}

API_KEY_HEADER = "X-API-Key"


def _parse_keys(raw: str) -> dict[str, int]:
    """Parse 'key:user_id,key:user_id' into a mapping."""
    keys: dict[str, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        key, _, uid = part.partition(":")
        if not key or not uid.isdigit():
            raise ValueError(f"invalid ITEMS_API_KEYS entry: {part!r}")
        keys[key] = int(uid)
    return keys


@dataclass
class Settings:
    db_path: str = ":memory:"
    api_keys: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_API_KEYS))
    default_page_size: int = DEFAULT_PAGE_SIZE
    max_page_size: int = MAX_PAGE_SIZE
    max_items_per_user: int = 1000

    @classmethod
    def from_env(cls) -> Settings:
        raw_keys = os.environ.get("ITEMS_API_KEYS")
        return cls(
            db_path=os.environ.get("ITEMS_DB_PATH", "items.db"),
            api_keys=_parse_keys(raw_keys) if raw_keys else dict(DEFAULT_API_KEYS),
            default_page_size=int(os.environ.get("ITEMS_PAGE_SIZE", DEFAULT_PAGE_SIZE)),
            max_page_size=int(os.environ.get("ITEMS_MAX_PAGE_SIZE", MAX_PAGE_SIZE)),
            max_items_per_user=int(os.environ.get("ITEMS_MAX_PER_USER", 1000)),
        )
