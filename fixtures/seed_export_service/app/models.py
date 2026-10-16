"""Pydantic request/response models."""
from __future__ import annotations

from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class UserOut(BaseModel):
    id: int
    name: str
    email: str


class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    quantity: int = Field(default=1, ge=0, le=1_000_000)


class ItemOut(BaseModel):
    id: int
    owner_id: int
    title: str
    slug: str
    description: Optional[str] = None
    quantity: int
    created_at: str


class Page(BaseModel, Generic[T]):
    items: List[T]
    total: int
    limit: int
    offset: int


class ItemPage(Page[ItemOut]):
    pass


class HealthOut(BaseModel):
    status: str
    version: str
