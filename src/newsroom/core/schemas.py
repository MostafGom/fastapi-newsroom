import base64
import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from newsroom.core.errors import AppError

UtcDatetime = Annotated[
    datetime,
    PlainSerializer(lambda d: d.isoformat().replace("+00:00", "Z"), return_type=str),
]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class ValidationErrorItem(BaseModel):
    loc: list[str | int]
    msg: str
    type: str | None = None


class Problem(BaseModel):
    """RFC 9457 problem details, as returned by every error response under ``/api``."""

    type: str = "about:blank"
    title: str
    status: int
    code: str
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[ValidationErrorItem] | None = None


class InvalidCursor(AppError):
    status_code = 400
    code = "invalid_cursor"


def encode_cursor(values: dict[str, Any]) -> str:
    raw = json.dumps(values, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidCursor("Malformed cursor") from exc
    if not isinstance(value, dict):
        raise InvalidCursor("Malformed cursor")
    return value


class PageParams(BaseModel):
    limit: int
    cursor: str | None


def page_params(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PageParams:
    return PageParams(limit=limit, cursor=cursor)


PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": Problem, "content": {"application/problem+json": {}}}
    for status in (400, 401, 403, 404, 409, 422)
}

Slug = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[\w-]+$")]
