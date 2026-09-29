import uuid

from fastapi import APIRouter, Depends, status

from newsroom.articles.schemas import ArticleSummaryOut
from newsroom.articles.service import ArticleService
from newsroom.auth.dependencies import CurrentReader, csrf_protect
from newsroom.core.db import DbSession
from newsroom.core.locale_dep import resolve_api_locale
from newsroom.core.schemas import PROBLEM_RESPONSES
from newsroom.users.schemas import ReaderProfileOut, ReaderProfileUpdate
from newsroom.users.service import UserService

router = APIRouter(
    prefix="/account",
    tags=["account"],
    responses=PROBLEM_RESPONSES,
    dependencies=[Depends(csrf_protect)],
)


def _profile(user) -> ReaderProfileOut:
    profile = user.reader_profile
    return ReaderProfileOut(
        email=user.email,
        display_name=profile.display_name if profile else None,
        preferred_locale=profile.preferred_locale if profile else None,
        newsletter_opt_in=profile.newsletter_opt_in if profile else False,
    )


@router.get("/profile", response_model=ReaderProfileOut)
async def get_profile(reader: CurrentReader) -> ReaderProfileOut:
    return _profile(reader.user)


@router.patch("/profile", response_model=ReaderProfileOut)
async def update_profile(
    payload: ReaderProfileUpdate, reader: CurrentReader, db: DbSession
) -> ReaderProfileOut:
    user = await UserService(db).update_reader_profile(
        reader.user,
        display_name=payload.display_name,
        preferred_locale=payload.preferred_locale,
        newsletter_opt_in=payload.newsletter_opt_in,
    )
    return _profile(user)


@router.get("/bookmarks", response_model=list[ArticleSummaryOut])
async def list_bookmarks(
    reader: CurrentReader, db: DbSession, locale: str = Depends(resolve_api_locale)
) -> list[ArticleSummaryOut]:
    return await ArticleService(db).list_bookmarks(reader.user.id, locale)


@router.post("/bookmarks/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_bookmark(article_id: uuid.UUID, reader: CurrentReader, db: DbSession) -> None:
    await ArticleService(db).bookmark(reader.user.id, article_id)


@router.delete("/bookmarks/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_bookmark(article_id: uuid.UUID, reader: CurrentReader, db: DbSession) -> None:
    await ArticleService(db).unbookmark(reader.user.id, article_id)
