import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from newsroom.audit.service import record_event
from newsroom.auth.principal import Principal
from newsroom.auth.service import utcnow
from newsroom.authz.permissions import Perm
from newsroom.core.config import Settings, get_settings
from newsroom.core.errors import Conflict, NotFound, PermissionDenied
from newsroom.media.models import MediaAsset, MediaTranslation
from newsroom.media.schemas import MediaOut, MediaTranslationIn

_MAX_BYTES = 8 * 1024 * 1024
_TYPES = {
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
    b"GIF87a": ("image/gif", "gif"),
    b"GIF89a": ("image/gif", "gif"),
    b"RIFF": ("image/webp", "webp"),
}


class MediaService:
    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    async def upload(
        self,
        actor: Principal,
        data: bytes,
        *,
        credit: str | None,
        filename: str | None = None,
    ) -> MediaOut:
        if not actor.grants.has_anywhere(Perm.MEDIA_UPLOAD):
            raise PermissionDenied("Missing permission: media.upload")
        if len(data) > _MAX_BYTES:
            raise Conflict("Image is larger than 8MB")
        mime, ext = _sniff(data)
        width, height = _dimensions(data, mime)
        asset_id = uuid.uuid7()
        key = f"{asset_id}.{ext}"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        _write_display(self._path(f"{asset_id}.display.jpg"), data)
        asset = MediaAsset(
            id=asset_id,
            storage_key=key,
            mime_type=mime,
            width=width,
            height=height,
            byte_size=len(data),
            filename=_filename(filename),
            credit=credit.strip() if credit else None,
            uploaded_by=actor.user.id,
            created_at=utcnow(),
        )
        self.db.add(asset)
        set_committed_value(asset, "translations", [])
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="media.uploaded",
            entity_type="media_asset",
            entity_id=asset.id,
            after={"mime_type": mime, "byte_size": len(data), "filename": asset.filename},
        )
        await self.db.commit()
        return MediaOut.model_validate(asset, from_attributes=True)

    async def set_translation(
        self, actor: Principal, asset_id: uuid.UUID, payload: MediaTranslationIn
    ) -> MediaOut:
        if not actor.grants.has_anywhere(Perm.MEDIA_MANAGE) and not actor.grants.has_anywhere(
            Perm.MEDIA_UPLOAD
        ):
            raise PermissionDenied("Missing permission: media.upload")
        if payload.locale not in self.settings.supported_locales:
            raise NotFound("Locale not found")
        asset = await self._get(asset_id)
        row = next((item for item in asset.translations if item.locale == payload.locale), None)
        if row is None:
            row = MediaTranslation(media_id=asset.id, locale=payload.locale)
            asset.translations.append(row)
        row.caption = _blank(payload.caption)
        row.alt_text = _blank(payload.alt_text)
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="media.captioned",
            entity_type="media_asset",
            entity_id=asset.id,
            after={"locale": payload.locale},
        )
        await self.db.commit()
        return MediaOut.model_validate(asset, from_attributes=True)

    async def rename(self, actor: Principal, asset_id: uuid.UUID, filename: str) -> MediaOut:
        if not actor.grants.has_anywhere(Perm.MEDIA_MANAGE) and not actor.grants.has_anywhere(
            Perm.MEDIA_UPLOAD
        ):
            raise PermissionDenied("Missing permission: media.upload")
        cleaned = _filename(filename)
        if cleaned is None:
            raise Conflict("Image name is empty")
        asset = await self._get(asset_id)
        asset.filename = cleaned
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="media.renamed",
            entity_type="media_asset",
            entity_id=asset.id,
            after={"filename": cleaned},
        )
        await self.db.commit()
        return MediaOut.model_validate(asset, from_attributes=True)

    async def _get(self, asset_id: uuid.UUID) -> MediaAsset:
        asset = await self.db.scalar(
            select(MediaAsset)
            .where(MediaAsset.id == asset_id)
            .options(selectinload(MediaAsset.translations))
        )
        if asset is None:
            raise NotFound("Media not found")
        return asset

    async def delete(self, actor: Principal, asset_id: uuid.UUID) -> None:
        """Delete an unused file. A lead image or a body image stays until the story lets go."""
        if not actor.grants.has_anywhere(Perm.MEDIA_MANAGE):
            raise PermissionDenied("Missing permission: media.manage")
        asset = await self._get(asset_id)
        if await self._in_use(asset.id):
            raise Conflict("Remove this image from stories before deleting it")
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="media.deleted",
            entity_type="media_asset",
            entity_id=asset.id,
            before={"storage_key": asset.storage_key, "mime_type": asset.mime_type},
        )
        for key in (asset.storage_key, f"{asset.id}.display.jpg"):
            path = self._path(key)
            if path.is_file():
                path.unlink()
        await self.db.delete(asset)
        await self.db.commit()

    async def _in_use(self, asset_id: uuid.UUID) -> bool:
        from newsroom.articles.models import Article, ArticleRevision

        lead = await self.db.scalar(
            select(Article.id).where(Article.lead_media_id == asset_id).limit(1)
        )
        if lead is not None:
            return True
        needle = f"/media/{asset_id}"
        used = await self.db.scalar(
            select(ArticleRevision.id)
            .where(cast(ArticleRevision.body, String).contains(needle))
            .limit(1)
        )
        return used is not None

    async def list_recent(self) -> list[MediaOut]:
        rows = (
            await self.db.scalars(
                select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(40)
            )
        ).all()
        return [MediaOut.model_validate(row, from_attributes=True) for row in rows]

    async def file(self, asset_id: uuid.UUID, *, original: bool = False) -> tuple[Path, str]:
        asset = await self.db.get(MediaAsset, asset_id)
        if asset is None:
            raise NotFound("Media not found")
        if not original:
            display = self._path(f"{asset.id}.display.jpg")
            if display.is_file():
                return display, "image/jpeg"
        path = self._path(asset.storage_key)
        if not path.is_file():
            raise NotFound("Media not found")
        return path, asset.mime_type

    async def caption(self, asset_id: uuid.UUID, locale: str) -> tuple[str | None, str | None]:
        asset = await self.db.scalar(
            select(MediaAsset)
            .where(MediaAsset.id == asset_id)
            .options(selectinload(MediaAsset.translations))
        )
        if asset is None:
            return None, None
        row = next((item for item in asset.translations if item.locale == locale), None)
        if row is None:
            return None, None
        return row.alt_text, row.caption

    def _path(self, key: str) -> Path:
        root = self.settings.media_dir.resolve()
        path = (root / key).resolve()
        if path.parent != root:
            raise NotFound("Media not found")
        return path


def _filename(raw: str | None) -> str | None:
    """Keep the name a person typed. The file on disk stays the asset id."""
    if raw is None:
        return None
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ord(ch) >= 32)
    name = name.strip().strip(".")
    if not name or name in {".", ".."}:
        return None
    return name[:200]


def _write_display(path: Path, data: bytes) -> None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            frame = image.convert("RGB")
            frame.thumbnail((1600, 1600))
            frame.save(path, format="JPEG", quality=82, optimize=True)
    except OSError, UnidentifiedImageError:
        return


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _sniff(data: bytes) -> tuple[str, str]:
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    for magic, found in _TYPES.items():
        if data.startswith(magic) and magic != b"RIFF":
            return found
    raise Conflict("File must be a JPEG, PNG, GIF, or WebP image")


def _dimensions(data: bytes, mime: str) -> tuple[int | None, int | None]:
    if mime == "image/png" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if mime == "image/gif" and len(data) >= 10:
        return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    if mime == "image/jpeg":
        return _jpeg_size(data)
    return None, None


def _jpeg_size(data: bytes) -> tuple[int | None, int | None]:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            break
        marker = data[index + 1]
        if marker in {0xC0, 0xC1, 0xC2}:
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return width, height
        if index + 4 > len(data):
            break
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        index += 2 + length
    return None, None
