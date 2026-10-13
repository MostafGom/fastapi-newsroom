import base64
import io
import uuid

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.audit.models import AuditEvent
from newsroom.core.config import Settings
from newsroom.media.models import MediaAsset
from newsroom.media.service import MAX_UPLOAD_BYTES, MediaService
from newsroom.seed.demo import DEMO_PASSWORD, READER_EMAIL, seed_demo
from tests.conftest import StaffAccount, api_login

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("1", (width, height)).save(out, format="PNG")
    return out.getvalue()


async def _editor(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    await seed_demo(db)
    editor = StaffAccount(id=None, email="demo-editor@example.com", password=DEMO_PASSWORD)
    return {"X-CSRF-Token": await api_login(client, editor)}


async def _assets(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(MediaAsset)) or 0


async def test_an_upload_is_refused_before_it_can_exhaust_the_server(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    headers = await _editor(client, db)
    files_before = set(settings.media_dir.iterdir())
    rows_before = await _assets(db)

    bomb = _png(10_000, 6_000)
    assert len(bomb) < 100_000
    refused = {
        "bomb": bomb,
        "unreadable": PNG[:40] + b"\x00" * 64,
        "oversized": PNG + b"\x00" * MAX_UPLOAD_BYTES,
    }
    for name, data in refused.items():
        response = await client.post(
            "/api/v1/admin/media",
            files={"file": (f"{name}.png", data, "image/png")},
            headers=headers,
        )
        assert response.status_code == 409, (name, response.text)
    long_credit = await client.post(
        "/api/v1/admin/media",
        files={"file": ("dot.png", PNG, "image/png")},
        data={"credit": "x" * 201},
        headers=headers,
    )
    assert long_credit.status_code == 409, long_credit.text

    assert await _assets(db) == rows_before
    assert set(settings.media_dir.iterdir()) == files_before

    accepted = await client.post(
        "/api/v1/admin/media",
        files={"file": ("wide.png", _png(4_000, 3_000), "image/png")},
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert (accepted.json()["width"], accepted.json()["height"]) == (4_000, 3_000)
    display = await client.get(f"/media/{accepted.json()['id']}")
    with Image.open(io.BytesIO(display.content)) as shown:
        assert shown.size == (1_600, 1_200)


async def test_a_failed_save_leaves_no_files(
    client: AsyncClient, db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await _editor(client, db)
    files_before = set(settings.media_dir.iterdir())

    async def fail() -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(db, "commit", fail)
    response = await client.post(
        "/api/v1/admin/media", files={"file": ("dot.png", PNG, "image/png")}, headers=headers
    )
    assert response.status_code == 500
    assert set(settings.media_dir.iterdir()) == files_before


def _located_jpeg() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x8825] = {1: "N", 2: (33.0, 51.0, 0.0)}
    out = io.BytesIO()
    Image.new("RGB", (40, 20), (200, 30, 30)).save(
        out, format="JPEG", exif=exif, comment=b"source-house"
    )
    return out.getvalue()


def _gps(data: bytes) -> dict:
    with Image.open(io.BytesIO(data)) as image:
        return dict(image.getexif().get_ifd(0x8825))


async def test_an_upload_keeps_no_location_and_the_original_is_for_staff_only(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    headers = await _editor(client, db)
    upload = _located_jpeg()
    assert _gps(upload)
    uploaded = await client.post(
        "/api/v1/admin/media", files={"file": ("shot.jpg", upload, "image/jpeg")}, headers=headers
    )
    assert uploaded.status_code == 200, uploaded.text
    asset = uploaded.json()
    assert (asset["width"], asset["height"]) == (20, 40)

    original = await client.get(f"/media/{asset['id']}/original")
    assert original.status_code == 200
    assert asset["byte_size"] == len(original.content)
    assert b"source-house" not in original.content
    assert _gps(original.content) == {}
    with Image.open(io.BytesIO(original.content)) as stored:
        assert dict(stored.getexif()) == {0x0112: 6}

    client.cookies.clear()
    display = await client.get(f"/media/{asset['id']}")
    assert display.status_code == 200
    with Image.open(io.BytesIO(display.content)) as shown:
        assert shown.size == (20, 40)
        assert not shown.getexif()
    assert (await client.get(f"/media/{asset['id']}/original")).status_code == 404

    reader = StaffAccount(id=None, email=READER_EMAIL, password=DEMO_PASSWORD)
    await api_login(client, reader, audience="reader")
    assert (await client.get(f"/media/{asset['id']}/original")).status_code == 404


async def test_strip_media_cleans_files_uploaded_before_stripping(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    headers = await _editor(client, db)
    uploaded = await client.post(
        "/api/v1/admin/media", files={"file": ("old.png", PNG, "image/png")}, headers=headers
    )
    asset_id = uploaded.json()["id"]
    stored = settings.media_dir / f"{asset_id}.png"
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Location", "source-house")
    out = io.BytesIO()
    Image.new("RGB", (1, 1)).save(out, format="PNG", pnginfo=info)
    stored.write_bytes(out.getvalue())
    # Uploads from before stripping had no untouched copy.
    (settings.media_dir / f"{asset_id}.source.png").unlink()

    changed, unreadable = await MediaService(db).strip_stored()

    assert changed == 1
    assert unreadable == 0
    assert b"source-house" not in stored.read_bytes()
    assert b"source-house" in (settings.media_dir / f"{asset_id}.source.png").read_bytes()
    asset = await db.get(MediaAsset, uuid.UUID(asset_id))
    assert asset is not None
    assert asset.byte_size == len(stored.read_bytes())
    assert await MediaService(db).strip_stored() == (0, 0)


async def test_only_a_super_admin_can_download_the_upload_as_received(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    headers = await _editor(client, db)
    upload = _located_jpeg()
    uploaded = await client.post(
        "/api/v1/admin/media", files={"file": ("shot.jpg", upload, "image/jpeg")}, headers=headers
    )
    asset_id = uploaded.json()["id"]
    source = f"/admin/media/{asset_id}/source"

    library = await client.get("/admin/media")
    assert source not in library.text
    assert (await client.get(source)).status_code == 403

    client.cookies.clear()
    assert (await client.get(source)).status_code != 200
    reader = StaffAccount(id=None, email=READER_EMAIL, password=DEMO_PASSWORD)
    await api_login(client, reader, audience="reader")
    assert (await client.get(source)).status_code != 200

    client.cookies.clear()
    chief = StaffAccount(id=None, email="demo-super@example.com", password=DEMO_PASSWORD)
    token = await api_login(client, chief)
    assert source in (await client.get("/admin/media")).text
    received = await client.get(source)
    assert received.status_code == 200
    assert received.content == upload
    assert _gps(received.content)
    assert received.headers["content-disposition"].startswith("attachment")
    assert "no-store" in received.headers["cache-control"]
    audited = await db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action == "media.source_downloaded",
            AuditEvent.entity_id == asset_id,
        )
    )
    assert audited == 1

    deleted = await client.delete(
        f"/api/v1/admin/media/{asset_id}", headers={"X-CSRF-Token": token}
    )
    assert deleted.status_code == 204, deleted.text
    assert not list(settings.media_dir.glob(f"{asset_id}*"))
