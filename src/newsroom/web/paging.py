"""Page numbers for HTML lists. The JSON API stays on opaque cursors."""

from typing import Annotated
from urllib.parse import urlencode

from fastapi import Query, Request

from newsroom.core.schemas import PageParams

MAX_PAGE = 20

PageQuery = Annotated[int, Query(ge=1, le=MAX_PAGE)]


def is_fragment(request: Request, cursor: str | None) -> bool:
    """HTMX "more" sends the cursor and expects only the next slice."""
    return request.headers.get("hx-request") == "true" and bool(cursor)


def listing_params(page_size: int, page: int, fragment: bool, cursor: str | None) -> PageParams:
    """A full visit shows every page up to ``page``. HTMX "more" fetches one slice."""
    return PageParams(
        limit=page_size if fragment else page_size * page,
        cursor=cursor if fragment else None,
    )


def listing_url(path: str, page: int, extra: dict[str, str] | None = None) -> str:
    query: dict[str, str] = {}
    if extra:
        query.update({key: value for key, value in extra.items() if value})
    if page > 1:
        query["page"] = str(page)
    if not query:
        return path
    return f"{path}?{urlencode(query)}"


def pager_context(
    *,
    path: str,
    page: int,
    extra: dict[str, str] | None,
    next_cursor: str | None,
    fragment: bool,
    prev_key: str,
    more_key: str,
) -> dict[str, object]:
    return {
        "page": page,
        "fragment": fragment,
        "next_cursor": next_cursor,
        "prev_href": listing_url(path, page - 1, extra),
        "more_href": listing_url(path, page + 1, extra),
        "prev_key": prev_key,
        "more_key": more_key,
    }
