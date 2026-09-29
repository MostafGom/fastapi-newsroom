from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.seed.demo import DEMO_PASSWORD, seed_demo
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
    assert [hit["slug"] for hit in politics.json()["items"]] == ["cabinet-budget"]
    sports = await client.get("/api/v1/search", params={"locale": "en", "section": "sports"})
    assert sports.json()["items"] == []
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
