"""Demo newsroom: staff, a reader, two desks, and a few stories. Idempotent."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.models import ArticleLocalization, Author
from newsroom.articles.schemas import (
    ArticleCreate,
    ArticleType,
    LocalizationCreate,
    RevisionContent,
    TransitionRequest,
)
from newsroom.articles.service import ArticleService
from newsroom.articles.workflow import ArticleAction, ArticleStatus
from newsroom.auth.principal import Principal
from newsroom.authz.authorizer import DbAuthorizer
from newsroom.core.schemas import PageParams
from newsroom.search.service import SearchService
from newsroom.taxonomy.models import Section, Tag
from newsroom.taxonomy.schemas import (
    SectionCreate,
    SectionTranslationIn,
    TagCreate,
    TagTranslationIn,
)
from newsroom.taxonomy.service import TaxonomyService
from newsroom.users.repository import UserRepository
from newsroom.users.service import UserService

DEMO_PASSWORD = "demo-password-123"  # noqa: S105

STAFF = (
    ("demo-super@example.com", "Demo Super", "super_admin", None),
    ("demo-editor@example.com", "Layla Nasser", "editor", "politics"),
    ("demo-copy@example.com", "Hana Saleh", "copy_editor", None),
    ("demo-writer@example.com", "Omar Haddad", "writer", None),
)
READER_EMAIL = "demo-reader@example.com"


def _doc(*paragraphs: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
            for text in paragraphs
        ],
    }


def _content(title: str, excerpt: str, *paragraphs: str) -> RevisionContent:
    return RevisionContent(title=title, excerpt=excerpt, body=_doc(*paragraphs))


async def seed_demo(db: AsyncSession) -> list[str]:
    notes = [f"demo password for every demo account: {DEMO_PASSWORD}"]
    politics_id = await _section(
        db,
        "politics",
        ("ar", "سياسة", "siyasa"),
        ("en", "Politics", "politics"),
    )
    await _section(db, "sports", ("ar", "رياضة", "riyada"), ("en", "Sports", "sports"))
    await _tag(db, "budget", ("ar", "موازنة", "muwazana"), ("en", "Budget", "budget"))

    users = UserService(db)
    repo = UserRepository(db)
    for email, name, role, section_key in STAFF:
        if await repo.get_by_email(email) is None:
            section_id = politics_id if section_key == "politics" else None
            await users.create_staff(
                email=email,
                display_name=name,
                password=DEMO_PASSWORD,
                role_key=role,
                section_id=section_id,
                job_title=role.replace("_", " "),
            )
            notes.append(f"created {role} {email}")
    if await repo.get_by_email(READER_EMAIL) is None:
        await users.register_reader(READER_EMAIL, DEMO_PASSWORD, "Nour Reader", "ar")
        notes.append(f"created reader {READER_EMAIL}")

    if await db.scalar(
        select(ArticleLocalization).where(ArticleLocalization.slug == "cabinet-budget")
    ):
        await _index_published(db)
        return notes

    writer = await _principal(db, "demo-writer@example.com")
    editor = await _principal(db, "demo-editor@example.com")
    copy_editor = await _principal(db, "demo-copy@example.com")
    author = await db.scalar(select(Author).where(Author.user_id == writer.user.id))
    if author is None:
        raise RuntimeError("demo writer has no author profile")
    tag_page = await TaxonomyService(db).list_tags(PageParams(limit=20, cursor=None), None)
    tag_ids = [item.id for item in tag_page.items if item.key == "budget"]

    articles = ArticleService(db)
    created = await articles.create(
        writer,
        ArticleCreate(
            section_id=politics_id,
            article_type=ArticleType.NEWS,
            author_ids=[author.id],
            tag_ids=tag_ids,
            locale="en",
            slug="cabinet-budget",
            content=_content(
                "Cabinet approves the 2027 budget",
                "The cabinet signed off on the budget after a late session.",
                "The cabinet approved the 2027 budget after a session that ran past midnight.",
                "The finance minister said the deficit target is unchanged.",
            ),
        ),
    )
    localization = next(item for item in created.localizations if item.locale == "en")
    await _walk(articles, writer, editor, copy_editor, localization.id, localization.lock_version)
    await articles.add_localization(
        writer,
        created.id,
        LocalizationCreate(
            locale="ar",
            slug="muwazana-2027",
            content=_content(
                "الحكومة تقر موازنة 2027",
                "أقرت الحكومة الموازنة بعد جلسة امتدت إلى ما بعد منتصف الليل.",
                "أقرت الحكومة موازنة 2027 بعد جلسة امتدت إلى ما بعد منتصف الليل.",
                "وقال وزير المالية إن هدف العجز لم يتغير.",
            ),
        ),
    )
    refreshed = await articles.get_admin(editor, created.id)
    arabic = next(item for item in refreshed.localizations if item.locale == "ar")
    await _walk(articles, writer, editor, copy_editor, arabic.id, arabic.lock_version)

    draft = await articles.create(
        writer,
        ArticleCreate(
            section_id=politics_id,
            author_ids=[author.id],
            locale="ar",
            slug="maswada-qanun",
            content=_content(
                "مسودة: مشروع قانون الانتخابات",
                "مسودة لم تُرسل بعد.",
                "هذه مسودة يعمل عليها الكاتب ولم تُرفع إلى الديسك.",
            ),
        ),
    )
    submitted = await articles.transition(
        writer,
        draft.localizations[0].id,
        TransitionRequest(
            action=ArticleAction.SUBMIT, lock_version=draft.localizations[0].lock_version
        ),
    )
    notes.append(f"story in review: {submitted.slug}")

    reader = await repo.get_by_email(READER_EMAIL)
    if reader is not None:
        await articles.bookmark(reader.id, created.id)
        notes.append("reader bookmarked the budget story")

    later = datetime.now(UTC) + timedelta(hours=6)
    scheduled = await articles.create(
        writer,
        ArticleCreate(
            section_id=politics_id,
            author_ids=[author.id],
            locale="en",
            slug="embargo-briefing",
            content=_content(
                "Embargoed briefing",
                "Scheduled to publish in six hours.",
                "This briefing is under embargo until the scheduled time.",
            ),
        ),
    )
    loc = scheduled.localizations[0]
    submitted = await articles.transition(
        writer,
        loc.id,
        TransitionRequest(action=ArticleAction.SUBMIT, lock_version=loc.lock_version),
    )
    approved = await articles.transition(
        editor,
        loc.id,
        TransitionRequest(
            action=ArticleAction.APPROVE,
            lock_version=submitted.lock_version,
            reason="embargo, copy already done",
        ),
    )
    await articles.transition(
        editor,
        loc.id,
        TransitionRequest(
            action=ArticleAction.SCHEDULE, lock_version=approved.lock_version, publish_at=later
        ),
    )
    notes.append("scheduled embargo-briefing for six hours from now")
    return notes


async def _index_published(db: AsyncSession) -> None:
    ids = list(
        (
            await db.scalars(
                select(ArticleLocalization.id).where(
                    ArticleLocalization.status == ArticleStatus.PUBLISHED
                )
            )
        ).all()
    )
    search = SearchService(db)
    for localization_id in ids:
        await search.sync(localization_id)
    await db.commit()


async def _section(db: AsyncSession, key: str, *translations: tuple[str, str, str]) -> uuid.UUID:
    existing = await db.scalar(select(Section).where(Section.key == key))
    if existing is not None:
        return existing.id
    created = await TaxonomyService(db).create_section(
        SectionCreate(
            key=key,
            translations=[
                SectionTranslationIn(locale=locale, name=name, slug=slug)
                for locale, name, slug in translations
            ],
        )
    )
    return created.id


async def _tag(db: AsyncSession, key: str, *translations: tuple[str, str, str]) -> None:
    if await db.scalar(select(Tag).where(Tag.key == key)):
        return
    await TaxonomyService(db).create_tag(
        TagCreate(
            key=key,
            translations=[
                TagTranslationIn(locale=locale, name=name, slug=slug)
                for locale, name, slug in translations
            ],
        )
    )


async def _principal(db: AsyncSession, email: str) -> Principal:
    user = await UserRepository(db).get_by_email(email)
    if user is None:
        raise RuntimeError(f"demo account {email} is missing")
    grants = await DbAuthorizer(db).grants_for(user.id)
    return Principal(user=user, session=None, grants=grants)  # type: ignore[arg-type]


async def _walk(
    articles: ArticleService,
    writer: Principal,
    editor: Principal,
    copy_editor: Principal,
    localization_id: uuid.UUID,
    lock: int,
) -> None:
    submitted = await articles.transition(
        writer,
        localization_id,
        TransitionRequest(action=ArticleAction.SUBMIT, lock_version=lock),
    )
    sent = await articles.transition(
        editor,
        localization_id,
        TransitionRequest(action=ArticleAction.SEND_TO_COPY, lock_version=submitted.lock_version),
    )
    signed = await articles.transition(
        copy_editor,
        localization_id,
        TransitionRequest(action=ArticleAction.FINISH_COPY, lock_version=sent.lock_version),
    )
    await articles.transition(
        editor,
        localization_id,
        TransitionRequest(action=ArticleAction.PUBLISH, lock_version=signed.lock_version),
    )
