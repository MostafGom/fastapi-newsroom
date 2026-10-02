import json

import httpx
import pytest
from pydantic import SecretStr

from newsroom.ai.client import AIError, describe_image, openrouter_configured, parse_description
from newsroom.core.config import get_settings


def _settings():
    return get_settings().model_copy(update={"openrouter_api_key": SecretStr("test-key")})


def _reply(content: str, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "google/gemini-2.5-flash"
        image = body["messages"][0]["content"][1]["image_url"]["url"]
        assert image.startswith("data:image/jpeg;base64,")
        return httpx.Response(
            status,
            json={"choices": [{"message": {"content": content}}]},
        )

    return httpx.MockTransport(handler)


async def test_describe_image_truncates_alt_text_and_keeps_each_locale() -> None:
    payload = {
        "ar": {"alt_text": "غرفة", "caption": "غرفة صغيرة."},
        "en": {"alt_text": "a" * 600, "caption": "A long\nroom."},
        "fr": {"alt_text": "ignored", "caption": "ignored"},
    }
    transport = _reply(json.dumps(payload))
    async with httpx.AsyncClient(transport=transport) as client:
        copies = await describe_image(
            b"\xff\xd8\xff",
            "image/jpeg",
            ["ar", "en"],
            settings=_settings(),
            client=client,
        )
    assert copies["ar"].alt_text == "غرفة"
    assert copies["ar"].caption == "غرفة صغيرة."
    assert copies["en"].alt_text == "a" * 500
    assert copies["en"].caption == "A long room."
    assert "fr" not in copies


async def test_describe_image_accepts_fenced_json() -> None:
    fenced = '```json\n{"en": {"alt_text": "A pixel", "caption": "One pixel."}}\n```'
    async with httpx.AsyncClient(transport=_reply(fenced)) as client:
        copies = await describe_image(
            b"\xff\xd8",
            "image/jpeg",
            ["en"],
            settings=_settings(),
            client=client,
        )
    assert copies["en"].alt_text == "A pixel"


async def test_describe_image_rejects_prose_and_http_errors() -> None:
    async with httpx.AsyncClient(transport=_reply("The photo shows a room.")) as client:
        with pytest.raises(AIError, match="not JSON"):
            await describe_image(
                b"\xff\xd8",
                "image/jpeg",
                ["en"],
                settings=_settings(),
                client=client,
            )
    async with httpx.AsyncClient(transport=_reply("{}", status=503)) as client:
        with pytest.raises(AIError, match="request failed"):
            await describe_image(
                b"\xff\xd8",
                "image/jpeg",
                ["en"],
                settings=_settings(),
                client=client,
            )


def test_parse_description_rejects_an_empty_reply() -> None:
    with pytest.raises(AIError, match="no captions"):
        parse_description('{"en": {"alt_text": "  ", "caption": "A pixel."}}', ["en"])


def test_blank_openrouter_key_is_not_configured() -> None:
    assert not openrouter_configured(get_settings())
