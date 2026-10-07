"""Coarse device and referrer labels. The raw User-Agent and address are not stored."""

import re
from urllib.parse import urlsplit

_BOT = re.compile(
    r"bot|spider|crawler|crawl|slurp|preview|facebookexternalhit|embedly|quora link",
    re.IGNORECASE,
)
_SEARCH = (
    "google.",
    "bing.com",
    "duckduckgo.com",
    "yahoo.",
    "yandex.",
    "baidu.com",
    "ecosia.org",
)
_SOCIAL = (
    "facebook.com",
    "fb.com",
    "instagram.com",
    "t.co",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "tiktok.com",
    "youtube.com",
    "reddit.com",
    "telegram.",
    "t.me",
    "whatsapp.",
    "threads.net",
)


def is_bot(user_agent: str | None) -> bool:
    return bool(user_agent and _BOT.search(user_agent))


def device_class(user_agent: str | None) -> str:
    ua = (user_agent or "").lower()
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "mobile" in ua or "iphone" in ua or "android" in ua:
        return "mobile"
    if not ua:
        return "other"
    return "desktop"


def referrer_class(referer: str | None, *site_hosts: str) -> str:
    if not referer:
        return "direct"
    host = (urlsplit(referer).hostname or "").lower().removeprefix("www.")
    if not host:
        return "direct"
    sites = {(item or "").lower().removeprefix("www.") for item in site_hosts if item}
    if host in sites or any(host.endswith(f".{site}") for site in sites if site):
        return "internal"
    if any(needle in host for needle in _SEARCH):
        return "search"
    if any(needle in host for needle in _SOCIAL):
        return "social"
    return "other"
