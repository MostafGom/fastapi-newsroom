import json
import re

from httpx import AsyncClient

from tests.conftest import MakeStaff

CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')


async def _login(client: AsyncClient, make_staff: MakeStaff) -> str:
    account = await make_staff("writer")
    form = await client.get("/admin/login")
    csrf = CSRF_FIELD.search(form.text)
    assert csrf is not None
    response = await client.post(
        "/admin/login",
        data={"csrf_token": csrf.group(1), "email": account.email, "password": account.password},
    )
    assert response.status_code == 303
    return account.email


async def test_editor_preview_renders_on_the_server(
    client: AsyncClient, make_staff: MakeStaff
) -> None:
    await _login(client, make_staff)
    page = await client.get("/admin/editor?dir=rtl")
    assert page.status_code == 200
    assert "data-richtext" in page.text
    assert 'data-dir="rtl"' in page.text
    assert 'data-cmd="h4"' in page.text
    assert 'data-cmd="undo"' in page.text
    assert 'data-cmd="code-block"' in page.text
    assert "data-word-count" in page.text
    assert "data-link-dialog" in page.text
    assert "اقتباس" in page.text
    csrf = CSRF_FIELD.search(page.text)
    assert csrf is not None

    preview = await client.post(
        "/admin/editor/preview",
        data={
            "csrf_token": csrf.group(1),
            "editor_dir": "rtl",
            "body": json.dumps(
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "<script>alert(1)</script>"}],
                        }
                    ],
                }
            ),
        },
    )
    assert preview.status_code == 200
    assert "<script>" not in preview.text
    assert "&lt;script&gt;" in preview.text
    assert 'dir="rtl"' in preview.text


async def test_editor_rejects_a_node_it_does_not_know(
    client: AsyncClient, make_staff: MakeStaff
) -> None:
    await _login(client, make_staff)
    page = await client.get("/admin/editor")
    csrf = CSRF_FIELD.search(page.text)
    assert csrf is not None
    preview = await client.post(
        "/admin/editor/preview",
        data={
            "csrf_token": csrf.group(1),
            "body": json.dumps({"type": "doc", "content": [{"type": "iframe"}]}),
        },
    )
    assert preview.status_code == 422
    assert "iframe" in preview.text
