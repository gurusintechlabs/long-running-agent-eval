"""API-key authentication stub: maps X-API-Key header values to user ids."""
from __future__ import annotations

from typing import Callable, Dict

from fastapi import Header, HTTPException, Request, status

from .config import API_KEY_HEADER


def resolve_user_id(api_keys: Dict[str, int], key: str | None) -> int:
    """Return the user id for ``key`` or raise 401."""
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing {API_KEY_HEADER} header",
        )
    user_id = api_keys.get(key)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key"
        )
    return user_id


def make_current_user_dependency() -> Callable[..., int]:
    """Build a FastAPI dependency returning the authenticated user id."""

    def current_user_id(
        request: Request,
        x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> int:
        return resolve_user_id(request.app.state.settings.api_keys, x_api_key)

    return current_user_id
