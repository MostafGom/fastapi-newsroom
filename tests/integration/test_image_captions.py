import base64

from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.ai.client import AIError, ImageCopy
from newsroom.audit.models import AuditEvent
from newsroom.core.config import Settings
from newsroom.seed.demo import DEMO_PASSWORD, seed_demo
from tests.conftest import StaffAccount, api_login

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def _upload(client: AsyncClient, db: AsyncSession) -> dict:
    await seed_demo(db)
    editor = StaffAccount(id=None, email="demo-editor@example.com", password=DEMO_PASSWORD)
    token = await api_login(client, editor)
    uploaded = await client.post(
        "/api/v1/admin/media",
        files={"file": ("dot.png", PNG, "image/png")},
        headers={"X-CSRF-Token": token},
    )
    assert uploaded.status_code == 200, uploaded.text
    return uploaded.json()


async def test_upload_saves_generated_captions(
    client: AsyncClient, db: AsyncSession, settings: Settings, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr("test-key"))

    async def fake(
        image: bytes,
        mime: str,
        locales: list[str],
        *,
        settings: Settings | None = None,
        client: object = None,
    ) -> dict[str, ImageCopy]:
        assert mime == "image/jpeg"
        assert image.startswith(b"\xff\xd8")
        assert locales == ["ar", "en"]
        return {
            "ar": ImageCopy(alt_text="نقطة", caption="نقطة واحدة."),
            "en": ImageCopy(alt_text="A pixel", caption="A single pixel."),
        }

    monkeypatch.setattr("newsroom.media.service.describe_image", fake)
    asset = await _upload(client, db)
    assert {
        (item["locale"], item["alt_text"], item["caption"]) for item in asset["translations"]
    } == {
        ("ar", "نقطة", "نقطة واحدة."),
        ("en", "A pixel", "A single pixel."),
    }
    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_id == asset["id"],
            AuditEvent.action == "media.captioned",
        )
    )
    assert event is not None
    assert event.after == {"generated_locales": ["ar", "en"]}


async def test_upload_keeps_the_file_when_the_model_fails(
    client: AsyncClient, db: AsyncSession, settings: Settings, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr("test-key"))

    async def fail(
        image: bytes,
        mime: str,
        locales: list[str],
        *,
        settings: Settings | None = None,
        client: object = None,
    ) -> dict[str, ImageCopy]:
        raise AIError("Model reply was not JSON")

    monkeypatch.setattr("newsroom.media.service.describe_image", fail)
    asset = await _upload(client, db)
    assert asset["mime_type"] == "image/png"
    assert asset["translations"] == []
