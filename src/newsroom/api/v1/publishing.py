import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from newsroom.articles.schemas import LeadImageUpdate
from newsroom.articles.service import ArticleService
from newsroom.auth.dependencies import csrf_protect
from newsroom.authz.dependencies import CurrentStaff, require_permission, require_staff
from newsroom.authz.permissions import Perm
from newsroom.core.db import DbSession
from newsroom.core.schemas import PROBLEM_RESPONSES
from newsroom.media.schemas import MediaNameIn, MediaOut, MediaTranslationIn
from newsroom.media.service import MediaService
from newsroom.pages.schemas import PageAdminOut, PageCreate, PageTranslationIn
from newsroom.pages.service import PageService

router = APIRouter(
    prefix="/admin",
    tags=["publishing"],
    responses=PROBLEM_RESPONSES,
    dependencies=[Depends(require_staff), Depends(csrf_protect)],
)


def can(perm: Perm) -> list:
    return [Depends(require_permission(perm))]


@router.post("/media", response_model=MediaOut, dependencies=can(Perm.MEDIA_UPLOAD))
async def upload_media(
    staff: CurrentStaff,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    credit: Annotated[str | None, Form()] = None,
) -> MediaOut:
    return await MediaService(db).upload(
        staff, await file.read(), credit=credit, filename=file.filename
    )


@router.put(
    "/media/{asset_id}/translations",
    response_model=MediaOut,
    dependencies=can(Perm.MEDIA_UPLOAD),
)
async def caption_media(
    asset_id: uuid.UUID, payload: MediaTranslationIn, staff: CurrentStaff, db: DbSession
) -> MediaOut:
    return await MediaService(db).set_translation(staff, asset_id, payload)


@router.put("/media/{asset_id}/name", response_model=MediaOut, dependencies=can(Perm.MEDIA_UPLOAD))
async def rename_media(
    asset_id: uuid.UUID, payload: MediaNameIn, staff: CurrentStaff, db: DbSession
) -> MediaOut:
    return await MediaService(db).rename(staff, asset_id, payload.filename)


@router.delete("/media/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(asset_id: uuid.UUID, staff: CurrentStaff, db: DbSession) -> None:
    await MediaService(db).delete(staff, asset_id)


@router.put("/articles/{article_id}/lead", status_code=status.HTTP_204_NO_CONTENT)
async def set_article_lead(
    article_id: uuid.UUID, payload: LeadImageUpdate, staff: CurrentStaff, db: DbSession
) -> None:
    await ArticleService(db).set_lead(staff, article_id, payload.media_id)


@router.get("/pages", response_model=list[PageAdminOut], dependencies=can(Perm.PAGE_MANAGE))
async def list_pages(staff: CurrentStaff, db: DbSession) -> list[PageAdminOut]:
    return await PageService(db).list_admin(staff)


@router.post(
    "/pages",
    response_model=PageAdminOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.PAGE_MANAGE),
)
async def create_page(payload: PageCreate, staff: CurrentStaff, db: DbSession) -> PageAdminOut:
    return await PageService(db).create(staff, payload)


@router.put(
    "/pages/{page_id}/translations",
    response_model=PageAdminOut,
    dependencies=can(Perm.PAGE_MANAGE),
)
async def save_page_translation(
    page_id: uuid.UUID, payload: PageTranslationIn, staff: CurrentStaff, db: DbSession
) -> PageAdminOut:
    return await PageService(db).save_translation(staff, page_id, payload)


@router.delete(
    "/pages/{page_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=can(Perm.PAGE_MANAGE),
)
async def delete_page(page_id: uuid.UUID, staff: CurrentStaff, db: DbSession) -> None:
    await PageService(db).delete(staff, page_id)
