import re

from httpx import AsyncClient

from newsroom.articles.workflow import TRANSITIONS
from tests.conftest import MakeStaff

CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')


async def test_every_staff_member_can_read_the_workflow(
    client: AsyncClient, make_staff: MakeStaff
) -> None:
    anonymous = await client.get("/admin/workflow", follow_redirects=False)
    assert anonymous.status_code == 303
    assert anonymous.headers["location"].startswith("/admin/login")

    account = await make_staff(None)
    form = await client.get("/admin/login")
    csrf = CSRF_FIELD.search(form.text)
    assert csrf is not None
    signed_in = await client.post(
        "/admin/login",
        data={"csrf_token": csrf.group(1), "email": account.email, "password": account.password},
        follow_redirects=False,
    )
    assert signed_in.status_code == 303

    page = await client.get("/admin/workflow")
    assert page.status_code == 200
    assert "كيف تصل المادة إلى النشر" in page.text
    assert 'href="/admin/workflow"' in page.text
    assert page.text.count("<tr>") == len(TRANSITIONS) + 1
    for action in TRANSITIONS:
        assert f"desk.action.{action.value}" not in page.text
    assert "article.submit" in page.text
    assert "article.copy" in page.text
    assert "article.publish" in page.text
    assert "article.unpublish" in page.text
    assert "article.archive" in page.text
    assert "article.delete_draft" in page.text
    assert "حُذفت" in page.text

    home = await client.get("/admin/")
    assert home.status_code == 200
    assert 'href="/admin/workflow"' in home.text
