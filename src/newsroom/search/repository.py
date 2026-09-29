"""Postgres full-text engine. Swap this module, not the routes, for another engine."""

import uuid
from datetime import datetime
from decimal import Decimal

import nh3
from sqlalchemy import Numeric, cast, delete, func, literal, literal_column, select, tuple_
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.core.schemas import Page, PageParams, decode_cursor, encode_cursor
from newsroom.search.models import SearchDocument
from newsroom.search.schemas import IndexedStory, SearchFilters, SearchHit

# A lexical match is enough. Results are then ordered by publication time, not by rank,
# so a later story is not buried because an older one repeats the word more often.
_RANK_THRESHOLD = 0.0
_HEADLINE = "StartSel=<mark>,StopSel=</mark>,MaxWords=28,MinWords=12"


def text_config(locale: str) -> str:
    return "arabic" if locale.split("-", 1)[0] == "ar" else "english"


def _regconfig(locale: str):
    return cast(literal(text_config(locale)), REGCONFIG)


def split_prefix_term(text: str) -> tuple[str, str | None]:
    """Prefix only a trailing bare word. Phrases and OR queries stay exact."""
    stripped = text.strip()
    if not stripped or '"' in stripped:
        return stripped, None
    parts = stripped.split()
    if any(part.upper() == "OR" for part in parts):
        return stripped, None
    last = parts[-1]
    if last.startswith("-") or not any(character.isalnum() for character in last):
        return stripped, None
    if len(parts) == 1:
        return "", last
    return " ".join(parts[:-1]), last


def _tsquery(locale: str, text: str):
    config = _regconfig(locale)
    normalized = func.search_normalize(text)
    exact = func.websearch_to_tsquery(config, normalized)
    head, last = split_prefix_term(text)
    if last is None:
        return exact
    prefix = func.search_prefix_tsquery(config, last)
    if not head:
        return func.coalesce(prefix, exact)
    earlier = func.websearch_to_tsquery(config, func.search_normalize(head))
    tail = func.coalesce(prefix, func.websearch_to_tsquery(config, func.search_normalize(last)))
    return earlier.op("&&")(tail)


def _vector(story: IndexedStory):
    config = _regconfig(story.locale)

    def weighted(value: str, weight: str):
        # Bound text becomes varchar; setweight wants the one-byte "char" type.
        # search_normalize folds Arabic before the stemmer sees it.
        return func.setweight(
            func.to_tsvector(config, func.search_normalize(value)),
            literal_column(f"'{weight}'"),
        )

    return (
        weighted(story.title, "A")
        .op("||")(weighted(story.excerpt or "", "B"))
        .op("||")(weighted(story.body_text, "C"))
        .op("||")(weighted(story.extra_text, "D"))
    )


class PostgresSearch:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert(self, story: IndexedStory) -> None:
        vector = _vector(story)
        values = {
            "localization_id": story.localization_id,
            "locale": story.locale,
            "slug": story.slug,
            "title": story.title,
            "excerpt": story.excerpt,
            "body_text": story.body_text,
            "section_id": story.section_id,
            "section_slug": story.section_slug,
            "section_name": story.section_name,
            "tag_slugs": story.tag_slugs,
            "published_at": story.published_at,
            "document": vector,
        }
        stmt = pg_insert(SearchDocument).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SearchDocument.localization_id],
            set_={key: stmt.excluded[key] for key in values if key != "localization_id"},
        )
        await self.db.execute(stmt)

    async def delete(self, localization_id: uuid.UUID) -> None:
        await self.db.execute(
            delete(SearchDocument).where(SearchDocument.localization_id == localization_id)
        )

    async def search(self, filters: SearchFilters, paging: PageParams) -> Page[SearchHit]:
        text = filters.text.strip()
        if not text and not any(
            (filters.section_slug, filters.tag_slug, filters.since, filters.until)
        ):
            return Page(items=[], next_cursor=None)
        stmt = select(SearchDocument).where(SearchDocument.locale == filters.locale)
        tsquery = None
        rank = literal(0)
        if text:
            tsquery = _tsquery(filters.locale, text)
            raw_rank = func.ts_rank_cd(SearchDocument.document, tsquery)
            rank = func.round(cast(raw_rank, Numeric), 6)
            stmt = stmt.where(SearchDocument.document.op("@@")(tsquery), raw_rank > _RANK_THRESHOLD)
        if filters.section_slug:
            stmt = stmt.where(SearchDocument.section_slug == filters.section_slug)
        if filters.tag_slug:
            stmt = stmt.where(SearchDocument.tag_slugs.contains([filters.tag_slug]))
        if filters.since is not None:
            stmt = stmt.where(SearchDocument.published_at >= filters.since)
        if filters.until is not None:
            stmt = stmt.where(SearchDocument.published_at <= filters.until)
        ordering = (
            (rank.desc(), SearchDocument.published_at.desc(), SearchDocument.localization_id.desc())
            if text
            else (SearchDocument.published_at.desc(), SearchDocument.localization_id.desc())
        )
        if paging.cursor:
            raw = decode_cursor(paging.cursor)
            published_at = datetime.fromisoformat(raw["published_at"])
            row_id = uuid.UUID(raw["id"])
            if text and "rank" in raw:
                stmt = stmt.where(
                    tuple_(rank, SearchDocument.published_at, SearchDocument.localization_id)
                    < tuple_(Decimal(raw["rank"]), published_at, row_id)
                )
            else:
                stmt = stmt.where(
                    tuple_(SearchDocument.published_at, SearchDocument.localization_id)
                    < tuple_(published_at, row_id)
                )
        stmt = stmt.order_by(*ordering).limit(paging.limit + 1)
        if text:
            found = (await self.db.execute(stmt.add_columns(rank))).all()
            pairs = [(row[0], row[1]) for row in found]
        else:
            pairs = [(row, None) for row in (await self.db.scalars(stmt)).all()]
        next_cursor = None
        if len(pairs) > paging.limit:
            pairs = pairs[: paging.limit]
            last, last_rank = pairs[-1]
            payload: dict[str, str] = {
                "published_at": last.published_at.isoformat(),
                "id": str(last.localization_id),
            }
            if last_rank is not None:
                payload["rank"] = str(last_rank)
            next_cursor = encode_cursor(payload)
        rows = [row for row, _rank in pairs]
        snippets = await self._snippets(rows, filters.locale, tsquery) if text else {}
        return Page(
            items=[_hit(row, snippets.get(row.localization_id), score) for row, score in pairs],
            next_cursor=next_cursor,
        )

    async def _snippets(self, rows: list[SearchDocument], locale: str, tsquery) -> dict:
        if not rows or tsquery is None:
            return {}
        ids = [row.localization_id for row in rows]
        source = func.search_normalize(
            func.concat(
                SearchDocument.title,
                literal(" "),
                func.coalesce(SearchDocument.excerpt, ""),
                literal(" "),
                SearchDocument.body_text,
            )
        )
        headline = func.ts_headline(_regconfig(locale), source, tsquery, literal(_HEADLINE))
        found = await self.db.execute(
            select(SearchDocument.localization_id, headline).where(
                SearchDocument.localization_id.in_(ids)
            )
        )
        return {row[0]: _clean_snippet(row[1]) for row in found.all()}


def _clean_snippet(value: str | None) -> str:
    if not value:
        return ""
    return nh3.clean(value, tags={"mark"})


def _hit(row: SearchDocument, snippet: str | None, rank: Decimal | None) -> SearchHit:
    shown = snippet or nh3.clean(row.excerpt or row.title)
    return SearchHit(
        localization_id=row.localization_id,
        locale=row.locale,
        slug=row.slug,
        title=row.title,
        section_name=row.section_name,
        section_slug=row.section_slug,
        published_at=row.published_at,
        snippet=shown,
        rank=float(rank) if rank is not None else None,
    )
