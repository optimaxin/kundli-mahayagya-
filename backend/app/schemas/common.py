from __future__ import annotations

import math
from typing import Any, Generic, Literal, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


class ApiResponse(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T
    meta: PageMeta | dict[str, Any] | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorBody
    request_id: str | None = None


class Pagination(BaseModel):
    model_config = ConfigDict(frozen=True)
    page: int = 1
    page_size: int = 25

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def meta(self, total: int) -> PageMeta:
        return PageMeta(
            page=self.page,
            page_size=self.page_size,
            total=total,
            total_pages=max(1, math.ceil(total / self.page_size)) if total else 0,
        )


def pagination_params(
    page: int = Query(1, ge=1, le=100_000, description="1-based page number"),
    page_size: int = Query(25, ge=1, le=200, description="Items per page (max 200)"),
) -> Pagination:
    return Pagination(page=page, page_size=page_size)


def ok(data: Any, meta: PageMeta | dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"success": True, "data": data}
    if meta is not None:
        body["meta"] = meta.model_dump() if isinstance(meta, BaseModel) else meta
    return body


class MessageOut(BaseModel):
    message: str = Field(..., examples=["OK"])
