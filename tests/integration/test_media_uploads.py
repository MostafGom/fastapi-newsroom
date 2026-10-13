import base64
import io

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.core.config import Settings
from newsroom.media.models import MediaAsset
from newsroom.media.service import MAX_UPLOAD_BYTES
from newsroom.seed.demo import DEMO_PASSWORD, seed_demo
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
