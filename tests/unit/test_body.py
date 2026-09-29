import pytest

from newsroom.articles.body import InvalidBody, plain_text, render_body


def _doc(*blocks: dict) -> dict:
    return {"type": "doc", "content": list(blocks)}


def _text(text: str, *marks: dict) -> dict:
    node: dict = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def test_renders_a_typical_news_lead() -> None:
    html = render_body(
        _doc(
            {
                "type": "paragraph",
                "content": [
                    _text("The minister "),
                    _text("denied", {"type": "bold"}),
                    _text(" the report."),
                ],
            },
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [_text("What we know")],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [_text("One")]}],
                    },
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    _text(
                        "the ruling",
                        {"type": "link", "attrs": {"href": "https://example.com/ruling"}},
                    )
                ],
            },
        )
    )
    assert "<strong>denied</strong>" in html
    assert "<h2>What we know</h2>" in html
    assert "<li><p>One</p></li>" in html
    assert 'href="https://example.com/ruling"' in html
    assert 'rel="noopener noreferrer"' in html


def test_escapes_text_and_rejects_unknown_nodes() -> None:
    html = render_body(_doc({"type": "paragraph", "content": [_text("<script>alert(1)</script>")]}))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    with pytest.raises(InvalidBody):
        render_body(_doc({"type": "iframe", "attrs": {"src": "https://evil.example"}}))


def test_rejects_unsafe_links_and_images_without_alt() -> None:
    with pytest.raises(InvalidBody):
        render_body(
            _doc(
                {
                    "type": "paragraph",
                    "content": [
                        _text("x", {"type": "link", "attrs": {"href": "javascript:alert(1)"}})
                    ],
                }
            )
        )
    media = "/media/01900000-0000-7000-8000-000000000001"
    with pytest.raises(InvalidBody):
        render_body(_doc({"type": "image", "attrs": {"src": media, "alt": "  "}}))
    with pytest.raises(InvalidBody):
        render_body(
            _doc({"type": "image", "attrs": {"src": "https://cdn.example/a.jpg", "alt": "x"}})
        )
    with pytest.raises(InvalidBody):
        render_body(_doc({"type": "image", "attrs": {"src": "/media/a.jpg", "alt": "x"}}))

    html = render_body(_doc({"type": "image", "attrs": {"src": media, "alt": "The chamber"}}))
    assert f'src="{media}"' in html
    assert 'alt="The chamber"' in html


def test_plain_text_keeps_words_and_image_alt() -> None:
    text = plain_text(
        _doc(
            {"type": "paragraph", "content": [_text("The cabinet"), _text("approved the budget.")]},
            {"type": "image", "attrs": {"src": "/media/a.jpg", "alt": "The chamber"}},
        )
    )
    assert text == "The cabinet approved the budget. The chamber"


def test_body_heading_cannot_be_h1() -> None:
    with pytest.raises(InvalidBody):
        render_body(_doc({"type": "heading", "attrs": {"level": 1}, "content": [_text("Title")]}))
