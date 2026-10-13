from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.search.service import SearchService
from newsroom.seed.demo import DEMO_PASSWORD, seed_demo
from newsroom.taxonomy.models import Section
from newsroom.taxonomy.schemas import TagCreate, TagTranslationIn
from newsroom.taxonomy.service import TaxonomyService
from tests.conftest import StaffAccount, api_login


def _localization(payload: dict, slug: str) -> dict:
    for article in payload["items"]:
        for item in article["localizations"]:
            if item["slug"] == slug:
                return item
    raise AssertionError(f"missing localization {slug}")


async def test_search_indexes_published_stories_and_drops_takedowns(
    client: AsyncClient, db: AsyncSession
) -> None:
    await seed_demo(db)

    english = await client.get("/api/v1/search", params={"locale": "en", "q": "budget"})
    assert english.status_code == 200, english.text
    hits = english.json()["items"]
    assert [hit["slug"] for hit in hits] == ["cabinet-budget"]
    assert "Cabinet" in hits[0]["title"]
    assert hits[0]["rank"] > 0
    assert "<mark>" in hits[0]["snippet"]
    assert "<script" not in hits[0]["snippet"]

    prefix = await client.get("/api/v1/search", params={"locale": "en", "q": "budg"})
    assert [hit["slug"] for hit in prefix.json()["items"]] == ["cabinet-budget"]

    arabic = await client.get("/api/v1/search", params={"locale": "ar", "q": "موازنة"})
    assert arabic.status_code == 200, arabic.text
    assert arabic.json()["items"][0]["slug"] == "muwazana-2027"
    folded = await client.get("/api/v1/search", params={"locale": "ar", "q": "موازنه"})
    assert folded.json()["items"][0]["slug"] == "muwazana-2027"

    draft = await client.get("/api/v1/search", params={"locale": "ar", "q": "مسودة"})
    assert draft.json()["items"] == []

    embargo = await client.get("/api/v1/search", params={"locale": "en", "q": "embargo"})
    assert embargo.json()["items"] == []

    blank = await client.get("/api/v1/search", params={"locale": "en"})
    assert blank.json()["items"] == []

    politics = await client.get("/api/v1/search", params={"locale": "en", "section": "politics"})
    assert {hit["slug"] for hit in politics.json()["items"]} == {
        "cabinet-budget",
        "editor-politics-note",
    }
    sports = await client.get("/api/v1/search", params={"locale": "en", "section": "sports"})
    assert {hit["slug"] for hit in sports.json()["items"]} == {
        "final-whistle",
        "transfer-window",
        "editor-sports-note",
    }
    tagged = await client.get("/api/v1/search", params={"locale": "en", "tag": "budget"})
    assert tagged.json()["items"][0]["slug"] == "cabinet-budget"

    page = await client.get("/en/search", params={"q": "budget"})
    assert page.status_code == 200
    assert "Cabinet approves the 2027 budget" in page.text
    assert "<mark>" in page.text

    editor = StaffAccount(id=None, email="demo-editor@example.com", password=DEMO_PASSWORD)
    token = await api_login(client, editor)
    headers = {"X-CSRF-Token": token}
    listed = await client.get("/api/v1/admin/articles")
    row = _localization(listed.json(), "cabinet-budget")
    renamed = await client.post(
        f"/api/v1/admin/localizations/{row['id']}/slug",
        json={"slug": "cabinet-budget-2027"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    found = await client.get("/api/v1/search", params={"locale": "en", "q": "budget"})
    assert [hit["slug"] for hit in found.json()["items"]] == ["cabinet-budget-2027"]

    taken = await client.post(
        f"/api/v1/admin/localizations/{row['id']}/transitions",
        json={
            "action": "unpublish",
            "lock_version": renamed.json()["lock_version"],
            "reason": "wrong figures",
            "takedown_reason": "major_error",
        },
        headers=headers,
    )
    assert taken.status_code == 200, taken.text
    gone = await client.get("/api/v1/search", params={"locale": "en", "q": "budget"})
    assert gone.json()["items"] == []


def _article(payload: dict, slug: str) -> dict:
    for article in payload["items"]:
        if any(item["slug"] == slug for item in article["localizations"]):
            return article
    raise AssertionError(f"missing article {slug}")


async def _slugs(client: AsyncClient, **params: str) -> set[str]:
    found = await client.get("/api/v1/search", params={"locale": "en", **params})
    assert found.status_code == 200, found.text
    return {hit["slug"] for hit in found.json()["items"]}


async def test_search_follows_section_tag_and_status_changes(
    client: AsyncClient, db: AsyncSession
) -> None:
    await seed_demo(db)
    sports = await db.scalar(select(Section).where(Section.key == "sports"))
    assert sports is not None
    fiscal = await TaxonomyService(db).create_tag(
        TagCreate(
            key="fiscal", translations=[TagTranslationIn(locale="en", name="Fiscal", slug="fiscal")]
        )
    )
    admin = StaffAccount(id=None, email="demo-super@example.com", password=DEMO_PASSWORD)
    headers = {"X-CSRF-Token": await api_login(client, admin)}
    article = _article(
        (await client.get("/api/v1/admin/articles", params={"q": "cabinet-budget"})).json(),
        "cabinet-budget",
    )
    lock = max(item["lock_version"] for item in article["localizations"])

    moved = await client.patch(
        f"/api/v1/admin/articles/{article['id']}",
        json={"lock_version": lock, "section_id": str(sports.id)},
        headers=headers,
    )
    assert moved.status_code == 200, moved.text
    assert "cabinet-budget" in await _slugs(client, section="sports")
    assert "cabinet-budget" not in await _slugs(client, section="politics")

    budget_tag = (await client.get("/api/v1/admin/tags", params={"q": "budget"})).json()["items"][0]
    merged = await client.post(
        "/api/v1/admin/tags/merge",
        json={"source_id": budget_tag["id"], "target_id": str(fiscal.id)},
        headers=headers,
    )
    assert merged.status_code == 200, merged.text
    assert "cabinet-budget" in await _slugs(client, tag="fiscal")
    assert await _slugs(client, tag="budget") == set()

    renamed = await client.patch(
        f"/api/v1/admin/sections/{sports.id}",
        json={
            "translations": [
                {"locale": "en", "name": "Sport", "slug": "sport"},
                {"locale": "ar", "name": "رياضة", "slug": "riyada-desk"},
            ]
        },
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert "cabinet-budget" in await _slugs(client, section="sport")
    assert await _slugs(client, section="sports") == set()

    row = _localization(
        (await client.get("/api/v1/admin/articles", params={"q": "cabinet-budget"})).json(),
        "cabinet-budget",
    )
    taken = await client.post(
        f"/api/v1/admin/localizations/{row['id']}/slug",
        json={"slug": "final-whistle"},
        headers=headers,
    )
    assert taken.status_code == 409, taken.text

    archived = await client.post(
        f"/api/v1/admin/localizations/{row['id']}/transitions",
        json={"action": "archive", "lock_version": row["lock_version"], "reason": "old"},
        headers=headers,
    )
    assert archived.status_code == 200, archived.text
    assert await _slugs(client, q="budget") == set()

    unarchived = await client.post(
        f"/api/v1/admin/localizations/{row['id']}/transitions",
        json={"action": "unarchive", "lock_version": archived.json()["lock_version"]},
        headers=headers,
    )
    assert unarchived.status_code == 200, unarchived.text
    assert await _slugs(client, q="budget") == set()


async def test_reindex_drops_documents_for_stories_that_are_no_longer_live(
    client: AsyncClient, db: AsyncSession
) -> None:
    await seed_demo(db)
    assert await _slugs(client, q="budget") == {"cabinet-budget"}
    # A story that left the live set before search followed every transition.
    await db.execute(
        text(
            "UPDATE article_localizations SET status = 'archived' "
            "WHERE slug = 'cabinet-budget' AND locale = 'en'"
        )
    )
    assert await _slugs(client, q="budget") == {"cabinet-budget"}

    assert await SearchService(db).reindex() > 0
    assert await _slugs(client, q="budget") == set()
    assert "final-whistle" in await _slugs(client, section="sports")
