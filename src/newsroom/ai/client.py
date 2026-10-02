import base64
import json
from dataclasses import dataclass

import httpx

from newsroom.core.config import Settings, get_settings

_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
_ALT_LIMIT = 500
_CAPTION_LIMIT = 2000


class AIError(Exception):
    """The model did not return usable text. Callers keep the upload."""


@dataclass(frozen=True, slots=True)
class ImageCopy:
    alt_text: str
    caption: str


def openrouter_configured(settings: Settings) -> bool:
    return _api_key(settings) is not None


async def complete(
    messages: list[dict[str, object]],
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Send a chat completion to OpenRouter and return the assistant text."""
    current = settings or get_settings()
    key = _api_key(current)
    if key is None:
        raise AIError("OpenRouter API key is not set")
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=current.openrouter_timeout_seconds)
    try:
        response = await http.post(
            _COMPLETIONS_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": current.openrouter_model, "messages": messages},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise AIError("OpenRouter request failed") from exc
    finally:
        if owns_client:
            await http.aclose()
    try:
        payload = response.json()
    except ValueError as exc:
        raise AIError("OpenRouter reply was not JSON") from exc
    return _message_text(payload)


async def describe_image(
    image: bytes,
    mime: str,
    locales: list[str],
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, ImageCopy]:
    """Ask for alt text and a caption in each locale. Raises AIError when the reply is unusable."""
    if not locales:
        raise AIError("No locales to describe")
    encoded = base64.b64encode(image).decode("ascii")
    messages: list[dict[str, object]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _instructions(locales)},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                },
            ],
        }
    ]
    return parse_description(
        await complete(messages, settings=settings, client=client),
        locales,
    )


def parse_description(raw: str, locales: list[str]) -> dict[str, ImageCopy]:
    text = _json_text(raw)
    if not text:
        raise AIError("Model reply was empty")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIError("Model reply was not JSON") from exc
    if not isinstance(data, dict):
        raise AIError("Model reply was not JSON")
    found: dict[str, ImageCopy] = {}
    for locale in locales:
        item = data.get(locale)
        if not isinstance(item, dict):
            continue
        alt_text = _clean(item.get("alt_text"), limit=_ALT_LIMIT)
        caption = _clean(item.get("caption"), limit=_CAPTION_LIMIT)
        if alt_text and caption:
            found[locale] = ImageCopy(alt_text=alt_text, caption=caption)
    if not found:
        raise AIError("Model reply had no captions")
    return found


def _api_key(settings: Settings) -> str | None:
    secret = settings.openrouter_api_key
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    return value or None


def _instructions(locales: list[str]) -> str:
    shape = ", ".join(f'"{code}": {{"alt_text": "...", "caption": "..."}}' for code in locales)
    return (
        "Describe this news photograph. Reply with JSON only, no markdown. "
        f"Use this shape: {{{shape}}}. "
        "Each locale needs alt_text and caption written in that language. "
        "alt_text is for a screen reader: state what is visible, and do not start with "
        "'image of' or 'photo of'. "
        "caption is one sentence a reader would see under the photo. "
        "Do not invent names, places, or dates that are not visible in the image."
    )


def _json_text(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _message_text(payload: object) -> str:
    if not isinstance(payload, dict):
        raise AIError("Model reply was empty")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AIError("Model reply was empty")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        text = "".join(parts).strip()
    else:
        text = ""
    if not text:
        raise AIError("Model reply was empty")
    return text


def _clean(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text[:limit]
