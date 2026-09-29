from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.service import author_for_user
from newsroom.taxonomy.schemas import SectionCreate, SectionTranslationIn
from newsroom.taxonomy.service import TaxonomyService
from tests.conftest import MakeStaff, api_login


def _doc(text: str) -> dict:
    paragraph = {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    return {"type": "doc", "content": [paragraph]}


async def test_revisions_can_be_listed_diffed_and_restored(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await TaxonomyService(db).create_section(
        SectionCreate(
            key="rev-desk",
            translations=[SectionTranslationIn(locale="en", name="Desk", slug="rev-desk")],
        )
    )
    writer = await make_staff("writer")
    editor = await make_staff("editor", section_id=section.id)
    author = await author_for_user(db, writer.id)  # type: ignore[arg-type]
    assert author is not None

    csrf = await api_login(client, writer)
    created = await client.post(
        "/api/v1/admin/articles",
        headers={"x-csrf-token": csrf},
        json={
            "section_id": str(section.id),
            "author_ids": [str(author.id)],
            "locale": "en",
            "slug": "rev-story",
            "content": {"title": "First headline", "body": _doc("First.")},
        },
    )
    assert created.status_code == 201, created.text
    localization_id = created.json()["localizations"][0]["id"]

    current = await client.get(f"/api/v1/admin/localizations/{localization_id}")
    assert current.status_code == 200
    base_id = current.json()["current_revision"]["id"]

    saved = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/revisions",
        headers={"x-csrf-token": csrf},
        json={
            "base_revision_id": base_id,
            "content": {"title": "Second headline", "body": _doc("Second.")},
        },
    )
    assert saved.status_code == 201, saved.text

    listed = await client.get(f"/api/v1/admin/localizations/{localization_id}/revisions")
    assert listed.status_code == 200
    numbers = [item["revision_no"] for item in listed.json()["items"]]
    assert numbers == [2, 1]

    diff = await client.get(
        f"/api/v1/admin/localizations/{localization_id}/revisions/{base_id}/diff/{saved.json()['id']}"
    )
    assert diff.status_code == 200
    fields = {item["field"]: item for item in diff.json()["fields"]}
    assert fields["title"]["before"] == "First headline"
    assert fields["title"]["after"] == "Second headline"
    assert "body[0]" in fields

    denied = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/revisions/{base_id}/restore",
        headers={"x-csrf-token": csrf},
        json={"base_revision_id": saved.json()["id"]},
    )
    assert denied.status_code == 403

    client.cookies.clear()
    editor_csrf = await api_login(client, editor)
    restored = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/revisions/{base_id}/restore",
        headers={"x-csrf-token": editor_csrf},
        json={"base_revision_id": saved.json()["id"], "change_note": "back to the first headline"},
    )
    assert restored.status_code == 201, restored.text
    body = restored.json()
    assert body["kind"] == "restore"
    assert body["restored_from_id"] == base_id
    assert body["content"]["title"] == "First headline"
    assert body["revision_no"] == 3
    paragraph = body["content"]["body"]["content"][0]
    assert paragraph["content"][0]["text"] == "First."

    page = await client.get(f"/admin/stories/{localization_id}")
    assert page.status_code == 200
    assert "Restore" in page.text or "استعادة" in page.text
