import uuid

from fastapi import APIRouter
from fastapi.responses import FileResponse

from newsroom.core.db import DbSession
from newsroom.media.service import MediaService

router = APIRouter(include_in_schema=False)


@router.get("/media/{asset_id}/original")
async def media_original(asset_id: uuid.UUID, db: DbSession) -> FileResponse:
    path, mime = await MediaService(db).file(asset_id, original=True)
    return FileResponse(path, media_type=mime)


@router.get("/media/{asset_id}")
async def media_file(asset_id: uuid.UUID, db: DbSession) -> FileResponse:
    path, mime = await MediaService(db).file(asset_id)
    return FileResponse(path, media_type=mime)
