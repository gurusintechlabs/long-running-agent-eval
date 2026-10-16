"""App factory and routes."""
from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status

from . import __version__, audit
from .auth import make_current_user_dependency
from .config import Settings
from .models import HealthOut, ItemCreate, ItemOut, ItemPage, UserOut
from .pagination import clamp_page
from .ratelimit import RateLimiter
from .store import Store

EXPORT_COLUMNS = ["id", "title", "slug", "description", "quantity", "created_at"]


def create_app(db_path: str = ":memory:", settings: Optional[Settings] = None) -> FastAPI:
    """Build an app with its own isolated store (and audit log)."""
    settings = settings or Settings(db_path=db_path)
    store = Store(settings.db_path)
    store.seed_users()
    audit.init(store.conn)

    app = FastAPI(title="Items Service", version=__version__)
    app.state.settings = settings
    app.state.store = store
    app.state.export_limiter = RateLimiter(
        settings.export_rate_limit, settings.export_rate_window_s
    )

    current_user_id = make_current_user_dependency()

    def get_store(request: Request) -> Store:
        return request.app.state.store

    @app.get("/health", response_model=HealthOut)
    def health() -> HealthOut:
        return HealthOut(status="ok", version=__version__)

    @app.get("/users/me", response_model=UserOut)
    def users_me(
        user_id: int = Depends(current_user_id), store: Store = Depends(get_store)
    ) -> dict:
        user = store.get_user(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        return user

    @app.get("/items", response_model=ItemPage)
    def list_items(
        request: Request,
        limit: Optional[int] = Query(default=None),
        offset: Optional[int] = Query(default=None),
        user_id: int = Depends(current_user_id),
        store: Store = Depends(get_store),
    ) -> dict:
        s = request.app.state.settings
        params = clamp_page(limit, offset, s.default_page_size, s.max_page_size)
        return {
            "items": store.list_items(user_id, params.limit, params.offset),
            "total": store.count_items(user_id),
            "limit": params.limit,
            "offset": params.offset,
        }

    @app.get("/export")
    def export_items(
        request: Request,
        limit: Optional[int] = Query(default=None),
        offset: Optional[int] = Query(default=None),
        user_id: int = Depends(current_user_id),
        store: Store = Depends(get_store),
    ) -> Response:
        s = request.app.state.settings
        allowed, retry_after = request.app.state.export_limiter.hit(user_id)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="export rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        params = clamp_page(limit, offset, s.default_page_size, s.max_page_size)
        rows = store.list_items(user_id, params.limit, params.offset)
        buf = io.StringIO(newline="")
        writer = csv.writer(buf)
        writer.writerow(EXPORT_COLUMNS)
        for r in rows:
            writer.writerow(
                [r["id"], r["title"], r["slug"], r["description"] or "",
                 r["quantity"], r["created_at"]]
            )
        audit.record(
            user_id,
            "export.csv",
            f"rows={len(rows)} limit={params.limit} offset={params.offset}",
        )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"X-Total-Count": str(store.count_items(user_id))},
        )

    @app.post("/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
    def create_item(
        body: ItemCreate,
        request: Request,
        user_id: int = Depends(current_user_id),
        store: Store = Depends(get_store),
    ) -> dict:
        cap = request.app.state.settings.max_items_per_user
        if store.count_items(user_id) >= cap:
            raise HTTPException(status_code=409, detail="item limit reached")
        item = store.create_item(
            user_id, body.title, body.description, body.quantity
        )
        audit.record(user_id, "item.create", f"id={item['id']} slug={item['slug']}")
        return item

    @app.get("/items/{item_id}", response_model=ItemOut)
    def get_item(
        item_id: int,
        user_id: int = Depends(current_user_id),
        store: Store = Depends(get_store),
    ) -> dict:
        item = store.get_item(user_id, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        return item

    @app.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_item(
        item_id: int,
        user_id: int = Depends(current_user_id),
        store: Store = Depends(get_store),
    ) -> Response:
        if not store.delete_item(user_id, item_id):
            raise HTTPException(status_code=404, detail="item not found")
        audit.record(user_id, "item.delete", f"id={item_id}")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn app.main:app_factory --factory``."""
    return create_app(settings=Settings.from_env())
