import uuid

from newsroom.analytics.classify import device_class, is_bot, referrer_class
from newsroom.analytics.desk import format_duration, scroll_share
from newsroom.analytics.ingest import RateGate
from newsroom.analytics.tokens import PageClaims, issue_page_token, read_page_token

SECRET = "test-secret"


def _claims() -> PageClaims:
    return PageClaims(
        surface="article",
        locale="ar",
        localization_id=uuid.uuid7(),
        article_id=uuid.uuid7(),
        section_id=uuid.uuid7(),
    )


def test_page_token_round_trip() -> None:
    claims = _claims()
    token = issue_page_token(SECRET, claims, ttl_seconds=60, now=1_000)
    assert read_page_token(SECRET, token, now=1_030) == claims


def test_page_token_rejects_tampering_and_expiry() -> None:
    token = issue_page_token(SECRET, _claims(), ttl_seconds=60, now=1_000)
    body, _, signature = token.partition(".")
    assert read_page_token(SECRET, f"{body}.{'0' * len(signature)}", now=1_010) is None
    assert read_page_token(SECRET, token, now=1_061) is None
    assert read_page_token("other-secret", token, now=1_010) is None


def test_referrer_and_device_classes() -> None:
    assert referrer_class(None, "news.example") == "direct"
    assert referrer_class("https://news.example/ar/", "news.example") == "internal"
    assert referrer_class("https://www.google.com/search?q=budget", "news.example") == "search"
    assert referrer_class("https://t.co/abc", "news.example") == "social"
    assert referrer_class("https://example.org/story", "news.example") == "other"
    assert device_class("Mozilla/5.0 (iPhone)") == "mobile"
    assert device_class("Mozilla/5.0 (iPad)") == "tablet"
    assert device_class("Mozilla/5.0") == "desktop"
    assert is_bot("Googlebot/2.1")
    assert not is_bot("Mozilla/5.0")


def test_rate_gate_drops_the_extra_event() -> None:
    gate = RateGate(limit=2, window_seconds=60)
    assert gate.allow("visitor", now=10)
    assert gate.allow("visitor", now=11)
    assert not gate.allow("visitor", now=12)
    assert gate.allow("visitor", now=71)


def test_duration_and_scroll_share() -> None:
    assert format_duration(7_500) == "0:07"
    assert format_duration(65_000) == "1:05"
    assert scroll_share(1, 2) == 50
    assert scroll_share(0, 0) == 0
