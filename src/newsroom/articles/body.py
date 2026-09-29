"""Render a TipTap document to HTML. The document is the source of truth; HTML is a cache.

Unknown nodes are rejected. `nh3` runs on the result so a bug in the renderer cannot
emit a tag the public site does not allow.
"""

from html import escape
from typing import Any
from urllib.parse import urlparse

import nh3

from newsroom.core.errors import AppError

MAX_NODES = 5_000

_ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "u",
    "s",
    "code",
    "pre",
    "a",
    "ul",
    "ol",
    "li",
    "blockquote",
    "h2",
    "h3",
    "h4",
    "hr",
    "img",
}
_ALLOWED_ATTRIBUTES = {
    "a": {"href"},
    "img": {"src", "alt"},
}
_MARKS = {
    "bold": ("strong", {}),
    "italic": ("em", {}),
    "underline": ("u", {}),
    "strike": ("s", {}),
    "code": ("code", {}),
}


class InvalidBody(AppError):
    status_code = 422
    code = "invalid_body"


def render_body(document: object) -> str:
    if not isinstance(document, dict) or document.get("type") != "doc":
        raise InvalidBody("Body must be a TipTap document")
    if _count(document) > MAX_NODES:
        raise InvalidBody("Body is too large")
    html = "".join(_block(node) for node in _children(document))
    return nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        url_relative="pass_through",
        link_rel="noopener noreferrer",
    )


def _count(node: object) -> int:
    if not isinstance(node, dict):
        return 1
    return 1 + sum(_count(child) for child in node.get("content") or [])


def _children(node: dict[str, Any]) -> list[dict[str, Any]]:
    content = node.get("content") or []
    if not isinstance(content, list):
        raise InvalidBody("Node content must be a list")
    for child in content:
        if not isinstance(child, dict) or "type" not in child:
            raise InvalidBody("Each node needs a type")
    return content


def _inline(node: dict[str, Any]) -> str:
    kind = node["type"]
    if kind == "text":
        if not isinstance(node.get("text"), str):
            raise InvalidBody("Text nodes need a string")
        html = escape(node["text"])
        for mark in node.get("marks") or []:
            html = _apply_mark(mark, html)
        return html
    if kind == "hardBreak":
        return "<br>"
    if kind == "image":
        return _image(node.get("attrs") or {})
    raise InvalidBody(f"Unknown inline node '{kind}'")


def _apply_mark(mark: object, html: str) -> str:
    if not isinstance(mark, dict) or not isinstance(mark.get("type"), str):
        raise InvalidBody("Invalid mark")
    kind = mark["type"]
    if kind == "link":
        href = _link_href((mark.get("attrs") or {}).get("href"))
        return f'<a href="{escape(href, quote=True)}">{html}</a>'
    pair = _MARKS.get(kind)
    if pair is None:
        raise InvalidBody(f"Unknown mark '{kind}'")
    tag, _ = pair
    return f"<{tag}>{html}</{tag}>"


def _block(node: dict[str, Any]) -> str:
    kind = node["type"]
    if kind == "paragraph":
        return f"<p>{_inlines(node)}</p>"
    if kind == "heading":
        level = (node.get("attrs") or {}).get("level", 2)
        if level not in (2, 3, 4):
            raise InvalidBody(
                "Headings in the body are h2, h3 or h4. The title is a separate field"
            )
        return f"<h{level}>{_inlines(node)}</h{level}>"
    if kind == "bulletList":
        return f"<ul>{''.join(_list_item(item) for item in _children(node))}</ul>"
    if kind == "orderedList":
        return f"<ol>{''.join(_list_item(item) for item in _children(node))}</ol>"
    if kind == "blockquote":
        inner = "".join(_block(child) for child in _children(node))
        return f"<blockquote>{inner}</blockquote>"
    if kind == "codeBlock":
        text = "".join(
            child.get("text", "") for child in _children(node) if child["type"] == "text"
        )
        return f"<pre><code>{escape(text)}</code></pre>"
    if kind == "horizontalRule":
        return "<hr>"
    if kind in {"text", "hardBreak", "image"}:
        return _inline(node)
    raise InvalidBody(f"Unknown block '{kind}'")


def _list_item(node: dict[str, Any]) -> str:
    if node["type"] != "listItem":
        raise InvalidBody("Lists contain only list items")
    return f"<li>{''.join(_block(child) for child in _children(node))}</li>"


def _inlines(node: dict[str, Any]) -> str:
    return "".join(_inline(child) for child in _children(node))


def _image(attrs: dict[str, Any]) -> str:
    src = attrs.get("src")
    alt = attrs.get("alt")
    if not isinstance(alt, str) or not alt.strip():
        raise InvalidBody("Images need alt text")
    if not isinstance(src, str) or not _is_allowed_url(src, relative_prefix="/media/"):
        raise InvalidBody("Image source must be a media path or an https URL")
    return f'<img src="{escape(src, quote=True)}" alt="{escape(alt, quote=True)}">'


def _link_href(href: object) -> str:
    if not isinstance(href, str) or not _is_allowed_url(href, relative_prefix="/"):
        raise InvalidBody("Link target must be an http(s), mailto, or site-relative URL")
    return href


def _is_allowed_url(value: str, *, relative_prefix: str) -> bool:
    if value.startswith(relative_prefix) and not value.startswith("//"):
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https", "mailto"} and bool(
        parsed.netloc or parsed.scheme == "mailto"
    )
