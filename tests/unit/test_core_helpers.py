import pytest

from newsroom.core.i18n import (
    TextDirection,
    interface_locales,
    locale_info,
    negotiate_locale,
    ordered_locales,
    parse_accept_language,
)
from newsroom.core.schemas import InvalidCursor, decode_cursor, encode_cursor
from newsroom.core.security import (
    csrf_token_is_valid,
    hash_password,
    hash_token,
    new_csrf_token,
    verify_password,
)


def test_password_roundtrip() -> None:
    hashed = hash_password("s3cret-passphrase")
    assert hashed.startswith("$argon2")
    assert verify_password("s3cret-passphrase", hashed)[0]
    assert not verify_password("wrong", hashed)[0]
    assert verify_password("anything", None) == (False, None)


def test_token_hash_is_stable_and_fixed_size() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert len(hash_token("abc")) == 32


def test_csrf_tokens_are_signed() -> None:
    token = new_csrf_token("key")
    assert csrf_token_is_valid("key", token)
    assert not csrf_token_is_valid("other-key", token)
    nonce = token.split(".", 1)[0]
    assert not csrf_token_is_valid("key", f"{nonce}.forged")
    assert not csrf_token_is_valid("key", None)


def test_cursor_roundtrip_and_rejects_garbage() -> None:
    values = {"published_at": "2026-09-29T00:00:00Z", "id": "abc"}
    assert decode_cursor(encode_cursor(values)) == values
    with pytest.raises(InvalidCursor):
        decode_cursor("!!!not-base64")


def test_accept_language_ordering() -> None:
    assert parse_accept_language("en-GB;q=0.8, ar, fr;q=0") == ["ar", "en-gb"]


@pytest.mark.parametrize(
    ("requested", "header", "expected"),
    [
        ("en", "ar", "en"),
        (None, "en-US,en;q=0.9", "en"),
        (None, "fr, de", "ar"),
        ("xx", None, "ar"),
    ],
)
def test_negotiate_locale(requested: str | None, header: str | None, expected: str) -> None:
    assert negotiate_locale(requested, header) == expected


def test_locale_direction() -> None:
    assert locale_info("ar").direction is TextDirection.RTL
    assert locale_info("en").direction is TextDirection.LTR


def test_default_locale_is_listed_first() -> None:
    assert ordered_locales(["en", "ar"], "ar") == ["ar", "en"]
    assert interface_locales(["en", "ar", "fr"], "ar") == ["ar", "en"]
