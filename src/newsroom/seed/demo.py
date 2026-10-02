"""Demo newsroom: a desk for each section, readers, and their stories. Idempotent."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.models import ArticleLocalization, Author
from newsroom.articles.schemas import (
    ArticleCreate,
    ArticleType,
    CorrectionCreate,
    LocalizationCreate,
    RevisionContent,
    TransitionRequest,
)
from newsroom.articles.service import ArticleService
from newsroom.articles.workflow import ArticleAction, ArticleStatus, CorrectionKind, TakedownReason
from newsroom.auth.principal import Principal
from newsroom.authz.authorizer import DbAuthorizer
from newsroom.comments.models import Comment
from newsroom.comments.service import CommentService
from newsroom.core.schemas import PageParams
from newsroom.pages.models import Page, PageStatus
from newsroom.pages.schemas import PageCreate, PageTranslationIn
from newsroom.pages.service import PageService
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

# section, writer email, editor email. Writers are unscoped. Editors are limited to the section.
DESKS = {
    "politics": ("demo-writer@example.com", "demo-editor@example.com"),
    "sports": ("demo-writer-sports@example.com", "demo-editor-sports@example.com"),
    "economy": ("demo-writer-economy@example.com", "demo-editor-economy@example.com"),
    "science": ("demo-writer-science@example.com", "demo-editor-science@example.com"),
    "culture": ("demo-writer-culture@example.com", "demo-editor-culture@example.com"),
}
STAFF = (
    ("demo-super@example.com", "Demo Super", "super_admin", None),
    ("demo-editor@example.com", "Layla Nasser", "editor", "politics"),
    ("demo-editor-sports@example.com", "Karim Mansour", "editor", "sports"),
    ("demo-editor-economy@example.com", "Nadia Qasem", "editor", "economy"),
    ("demo-editor-science@example.com", "Tariq Hilal", "editor", "science"),
    ("demo-editor-culture@example.com", "Dina Barakat", "editor", "culture"),
    ("demo-copy@example.com", "Hana Saleh", "copy_editor", None),
    ("demo-writer@example.com", "Omar Haddad", "writer", None),
    ("demo-writer-sports@example.com", "Rami Khoury", "writer", None),
    ("demo-writer-economy@example.com", "Maya Faris", "writer", None),
    ("demo-writer-science@example.com", "Samir Awad", "writer", None),
    ("demo-writer-culture@example.com", "Lina Darwish", "writer", None),
)
READERS = (
    ("demo-reader@example.com", "Nour Reader", "ar"),
    ("demo-reader-yusuf@example.com", "Yusuf Amin", "en"),
    ("demo-reader-sara@example.com", "Sara Haddad", "ar"),
    ("demo-reader-leila@example.com", "Leila Mansour", "en"),
    ("demo-reader-fadi@example.com", "Fadi Nasser", "ar"),
    ("demo-reader-huda@example.com", "Huda Saleh", "en"),
)
READER_EMAIL = "demo-reader@example.com"
# reader email, published slug, comment body. Each reader appears twice.
_COMMENTS = (
    ("demo-reader@example.com", "muwazana-2027", "الجلسة طالت، والرقم يحتاج إلى جدول أوضح."),
    ("demo-reader@example.com", "final-whistle", "The equalizer changed the night."),
    ("demo-reader-yusuf@example.com", "cabinet-budget", "The late session is the useful part."),
    ("demo-reader-yusuf@example.com", "transfer-window", "The fee note belongs at the top."),
    ("demo-reader-sara@example.com", "muwazana-2027", "هل نُشر جدول العجز مع الخبر؟"),
    ("demo-reader-sara@example.com", "editor-politics-note", "A short note is easier to follow."),
    ("demo-reader-leila@example.com", "editor-sports-note", "The fixture list is what I came for."),
    ("demo-reader-leila@example.com", "writer-economy-note", "The shop hours are the useful line."),
    ("demo-reader-fadi@example.com", "muwazana-2027", "الخبر واضح، والتوقيت أهم من الصياغة."),
    ("demo-reader-fadi@example.com", "writer-science-note", "The gauge repair is the fact."),
    ("demo-reader-huda@example.com", "writer-culture-note", "The lineup is enough."),
    ("demo-reader-huda@example.com", "editor-culture-note", "Name the hall next time."),
)
_BOOKMARKS = (
    ("demo-reader-yusuf@example.com", "transfer-window"),
    ("demo-reader-sara@example.com", "editor-politics-note"),
    ("demo-reader-leila@example.com", "editor-sports-note"),
    ("demo-reader-fadi@example.com", "writer-science-note"),
    ("demo-reader-huda@example.com", "writer-culture-note"),
)


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
    sections = await _sections(db)
    await _tag(db, "budget", ("ar", "موازنة", "muwazana"), ("en", "Budget", "budget"))

    users = UserService(db)
    repo = UserRepository(db)
    for email, name, role, section_key in STAFF:
        if await repo.get_by_email(email) is None:
            await users.create_staff(
                email=email,
                display_name=name,
                password=DEMO_PASSWORD,
                role_key=role,
                section_id=sections.get(section_key) if section_key else None,
                job_title=role.replace("_", " "),
            )
            notes.append(f"created {role} {email}")
    for email, name, locale in READERS:
        if await repo.get_by_email(email) is None:
            await users.register_reader(email, DEMO_PASSWORD, name, locale)
            notes.append(f"created reader {email}")

    writer = await _principal(db, "demo-writer@example.com")
    editor = await _principal(db, "demo-editor@example.com")
    copy_editor = await _principal(db, "demo-copy@example.com")
    super_admin = await _principal(db, "demo-super@example.com")
    sports_writer = await _principal(db, DESKS["sports"][0])
    sports_editor = await _principal(db, DESKS["sports"][1])
    await _seed_pages(db, super_admin)
    author_id = await _author_id(db, writer.user.email)
    sports_author_id = await _author_id(db, sports_writer.user.email)
    articles = ArticleService(db)
    if await _missing(db, "cabinet-budget"):
        await _seed_original(
            db, articles, writer, editor, copy_editor, author_id, sections["politics"], repo, notes
        )
    await _seed_variations(
        db,
        articles,
        writer,
        editor,
        copy_editor,
        super_admin,
        author_id,
        sports_writer,
        sports_editor,
        sports_author_id,
        sections["politics"],
        sections["sports"],
    )
    await _seed_signed(db, articles, copy_editor, sections)
    await _seed_reader_notes(db, articles)
    if not await _missing(db, "cabinet-budget"):
        await _index_published(db)
    return notes


async def _sections(db: AsyncSession) -> dict[str, uuid.UUID]:
    return {
        "politics": await _section(
            db, "politics", ("ar", "سياسة", "siyasa"), ("en", "Politics", "politics")
        ),
        "sports": await _section(
            db, "sports", ("ar", "رياضة", "riyada"), ("en", "Sports", "sports")
        ),
        "economy": await _section(
            db, "economy", ("ar", "اقتصاد", "iqtisad"), ("en", "Economy", "economy")
        ),
        "science": await _section(
            db, "science", ("ar", "علوم", "ulum"), ("en", "Science", "science")
        ),
        "culture": await _section(
            db, "culture", ("ar", "ثقافة", "thaqafa"), ("en", "Culture", "culture")
        ),
    }


async def _seed_original(
    db: AsyncSession,
    articles: ArticleService,
    writer: Principal,
    editor: Principal,
    copy_editor: Principal,
    author_id: uuid.UUID,
    politics_id: uuid.UUID,
    repo: UserRepository,
    notes: list[str],
) -> None:
    tag_page = await TaxonomyService(db).list_tags(PageParams(limit=20, cursor=None), None)
    tag_ids = [item.id for item in tag_page.items if item.key == "budget"]

    created = await articles.create(
        writer,
        ArticleCreate(
            section_id=politics_id,
            article_type=ArticleType.NEWS,
            author_ids=[author_id],
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
            author_ids=[author_id],
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
            author_ids=[author_id],
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


async def _author_id(db: AsyncSession, email: str) -> uuid.UUID:
    user = await UserRepository(db).get_by_email(email)
    if user is None:
        raise RuntimeError(f"demo account {email} is missing")
    author = await db.scalar(select(Author).where(Author.user_id == user.id))
    if author is None:
        raise RuntimeError(f"demo account {email} has no author profile")
    return author.id


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


_PAGES: tuple[tuple[int, str, tuple[tuple[str, str, str, str, str], ...]], ...] = (
    (
        1,
        "about",
        (
            (
                "en",
                "About",
                "about",
                "This paper publishes reported news in Arabic and English.",
                "Each language edition is edited on its own. A draft stays off the site.",
            ),
            (
                "ar",
                "عن الموقع",
                "an-al-mawqie",
                "تنشر هذه الصحيفة أخباراً مبنية على التقرير بالعربية والإنجليزية.",
                "لكل لغة من المادة مسار تحرير ونشر مستقل. المسودة لا تظهر في الموقع.",
            ),
        ),
    ),
    (
        2,
        "contact",
        (
            (
                "en",
                "Contact",
                "contact",
                "News tips reach the desk at desk@example.com.",
                "Name the story and its language. The desk does not reply to every message.",
            ),
            (
                "ar",
                "اتصل بنا",
                "ittasil",
                "تصل بلاغات الأخبار إلى الديسك على desk@example.com.",
                "اذكر عنوان المادة وطبعتها اللغوية. لا يرد الديسك على كل رسالة.",
            ),
        ),
    ),
    (
        3,
        "corrections",
        (
            (
                "en",
                "Corrections",
                "corrections",
                "A factual mistake is fixed on the same page, with a note of what was wrong.",
                "If the story should not stay up, the desk takes it down. The old address says so.",
            ),
            (
                "ar",
                "التصحيحات",
                "tashih",
                "يُصحَّح الخطأ الوقائعي على الصفحة نفسها، مع ملاحظة تبيّن ما كان خطأ.",
                "إذا لم يعد نشر المادة جائزاً، يسحبها الديسك. العنوان القديم يبيّن أن المادة رُفعت.",
            ),
        ),
    ),
    (
        4,
        "privacy",
        (
            (
                "en",
                "Privacy",
                "privacy",
                "A reader account stores an email, a display name, and the briefing choice.",
                "The site does not sell that record. Staff accounts are separate.",
            ),
            (
                "ar",
                "الخصوصية",
                "khususiyya",
                "يحفظ حساب القارئ عنوان البريد والاسم الظاهر، وهل طلب النشرة اليومية.",
                "لا يُباع هذا السجل. حسابات التحرير منفصلة عن حسابات القراء.",
            ),
        ),
    ),
)


async def _seed_pages(db: AsyncSession, actor: Principal) -> None:
    pages = PageService(db)
    for sort_order, key, locales in _PAGES:
        if await db.scalar(select(Page.id).where(Page.key == key)) is not None:
            continue
        created = await pages.create(actor, PageCreate(key=key, sort_order=sort_order))
        for locale, title, slug, *paragraphs in locales:
            await pages.save_translation(
                actor,
                created.id,
                PageTranslationIn(
                    locale=locale,
                    title=title,
                    slug=slug,
                    body=_doc(*paragraphs),
                    status=PageStatus.PUBLISHED,
                ),
            )


async def _seed_variations(
    db: AsyncSession,
    articles: ArticleService,
    writer: Principal,
    editor: Principal,
    copy_editor: Principal,
    super_admin: Principal,
    author_id: uuid.UUID,
    sports_writer: Principal,
    sports_editor: Principal,
    sports_author_id: uuid.UUID,
    politics_id: uuid.UUID,
    sports_id: uuid.UUID,
) -> None:
    if await _missing(db, "city-hall-notes"):
        await _file(
            articles,
            writer,
            author_id,
            politics_id,
            "city-hall-notes",
            _content(
                "Notes from the Tuesday council session",
                "The writer has not filed this yet.",
                "The council discussed a zoning appeal. The draft is still on the writer's desk.",
            ),
        )
    if await _missing(db, "port-lease"):
        loc_id, lock = await _file(
            articles,
            writer,
            author_id,
            politics_id,
            "port-lease",
            _content(
                "Port authority reviews the lease",
                "Copy is reading the lease story.",
                "The port authority opened the lease file. The copy desk has the story.",
            ),
        )
        await _to_copy(articles, writer, editor, loc_id, lock)
    if await _missing(db, "quote-check"):
        loc_id, lock = await _file(
            articles,
            writer,
            author_id,
            politics_id,
            "quote-check",
            _content(
                "Minister's quote needs a name",
                "The desk sent this back.",
                "A minister commented on the talks. The desk asked who said it.",
            ),
        )
        lock = await _move(articles, writer, loc_id, lock, ArticleAction.SUBMIT)
        await _move(
            articles,
            editor,
            loc_id,
            lock,
            ArticleAction.REQUEST_CHANGES,
            reason="The quote has no name.",
        )
    if await _missing(db, "minister-travel"):
        loc_id, lock = await _file(
            articles,
            writer,
            author_id,
            politics_id,
            "minister-travel",
            _content(
                "Minister's travel schedule is ready",
                "Copy signed off. It is not scheduled.",
                "The minister's office published the week's travel. Copy has signed the story off.",
            ),
        )
        await _to_approved(articles, writer, editor, copy_editor, loc_id, lock)
    if await _missing(db, "wire-duplicate"):
        loc_id, lock = await _file(
            articles,
            writer,
            author_id,
            politics_id,
            "wire-duplicate",
            _content(
                "Wire copy of the afternoon ruling",
                "Spiked because another desk already had it.",
                "The ruling arrived on the wire. The desk spiked it.",
            ),
        )
        lock = await _move(articles, writer, loc_id, lock, ArticleAction.SUBMIT)
        await _move(
            articles,
            editor,
            loc_id,
            lock,
            ArticleAction.KILL,
            reason="The other paper had it first.",
        )
    if await _missing(db, "company-investigation"):
        loc_id, lock = await _file(
            articles,
            writer,
            author_id,
            politics_id,
            "company-investigation",
            _content(
                "Company named in the draft inquiry",
                "Held for counsel.",
                "The draft names a company. It cannot go live until counsel is recorded.",
            ),
        )
        await _to_approved(articles, writer, editor, copy_editor, loc_id, lock)
        await articles.set_legal_hold(
            editor, loc_id, "The draft names a company before counsel has read it."
        )
    if await _missing(db, "court-letter"):
        loc_id, lock = await _file(
            articles,
            writer,
            author_id,
            politics_id,
            "court-letter",
            _content(
                "Court asked for a letter to come down",
                "Published, then taken down for a legal reason.",
                "The court wrote to the desk about a letter quoted in the story.",
            ),
        )
        lock = await _to_published(articles, writer, editor, copy_editor, loc_id, lock)
        await _move(
            articles,
            editor,
            loc_id,
            lock,
            ArticleAction.UNPUBLISH,
            reason="Counsel asked for the letter to come down.",
            takedown_reason=TakedownReason.LEGAL,
        )
    if await _missing(db, "named-witness"):
        loc_id, lock = await _file(
            articles,
            writer,
            author_id,
            politics_id,
            "named-witness",
            _content(
                "Witness could be identified",
                "Taken down to avoid harm.",
                "The story described a witness in enough detail to identify them.",
            ),
        )
        lock = await _to_published(articles, writer, editor, copy_editor, loc_id, lock)
        await _move(
            articles,
            editor,
            loc_id,
            lock,
            ArticleAction.UNPUBLISH,
            reason="The witness is identifiable.",
            takedown_reason=TakedownReason.SAFETY,
        )
    if await _missing(db, "old-session"):
        loc_id, lock = await _file(
            articles,
            writer,
            author_id,
            politics_id,
            "old-session",
            _content(
                "Last year's opening session",
                "Published, then archived.",
                "The opening session of the previous term is no longer in the active file.",
            ),
        )
        lock = await _to_published(articles, writer, editor, copy_editor, loc_id, lock)
        await _move(articles, super_admin, loc_id, lock, ArticleAction.ARCHIVE)
        await SearchService(db).sync(loc_id)
        await db.commit()
    if await _missing(db, "final-whistle"):
        loc_id, lock = await _file(
            articles,
            sports_writer,
            sports_author_id,
            sports_id,
            "final-whistle",
            _content(
                "Final whistle in the cup tie",
                "Taken down as a duplicate, then put back.",
                "The cup tie ended level. The desk pulled the story, then published it again.",
            ),
        )
        lock = await _to_published(
            articles, sports_writer, sports_editor, copy_editor, loc_id, lock
        )
        lock = await _move(
            articles,
            sports_editor,
            loc_id,
            lock,
            ArticleAction.UNPUBLISH,
            reason="Same result as the wire.",
            takedown_reason=TakedownReason.DUPLICATE,
        )
        await _move(articles, sports_editor, loc_id, lock, ArticleAction.REPUBLISH)
    if await _missing(db, "transfer-window"):
        loc_id, lock = await _file(
            articles,
            sports_writer,
            sports_author_id,
            sports_id,
            "transfer-window",
            _content(
                "Club confirms the signing",
                "A fee in the first version was wrong.",
                "The club confirmed a signing on the last day of the window.",
            ),
        )
        await _to_published(articles, sports_writer, sports_editor, copy_editor, loc_id, lock)
        await articles.add_correction(
            sports_editor,
            loc_id,
            CorrectionCreate(kind=CorrectionKind.CORRECTION, text="The fee was 4 million, not 40."),
        )


async def _seed_signed(
    db: AsyncSession,
    articles: ArticleService,
    copy_editor: Principal,
    sections: dict[str, uuid.UUID],
) -> None:
    """One signed note from each editor, and one story from each new writer."""
    for section_key, email, slug, content in _EDITOR_NOTES:
        if not await _missing(db, slug):
            continue
        editor = await _principal(db, email)
        await _publish_own(
            articles,
            editor,
            copy_editor,
            await _author_id(db, email),
            sections[section_key],
            slug,
            content,
        )
    for section_key, email, slug, content in _WRITER_STORIES:
        if not await _missing(db, slug):
            continue
        writer = await _principal(db, email)
        editor = await _principal(db, DESKS[section_key][1])
        loc_id, lock = await _file(
            articles,
            writer,
            await _author_id(db, email),
            sections[section_key],
            slug,
            content,
        )
        await _to_published(articles, writer, editor, copy_editor, loc_id, lock)


_EDITOR_NOTES = (
    (
        "politics",
        "demo-editor@example.com",
        "editor-politics-note",
        _content(
            "From the politics desk",
            "What the desk is watching this week.",
            "The politics desk is following the week's committee calendar.",
            "A vote that slips the agenda will be filed as its own story.",
        ),
    ),
    (
        "sports",
        "demo-editor-sports@example.com",
        "editor-sports-note",
        _content(
            "From the sports desk",
            "The fixture list for the week.",
            "The sports desk is holding the week's fixture list.",
            "A result that changes after publication gets a correction on the same page.",
        ),
    ),
    (
        "economy",
        "demo-editor-economy@example.com",
        "editor-economy-note",
        _content(
            "From the economy desk",
            "What the business desk is checking.",
            "The economy desk is checking delivery notes from the port and the shops.",
            "A figure that is still an estimate stays out of the headline.",
        ),
    ),
    (
        "science",
        "demo-editor-science@example.com",
        "editor-science-note",
        _content(
            "From the science desk",
            "The lab visits on the list.",
            "The science desk is booking two lab visits this week.",
            "A reading that is not confirmed stays in the notebook.",
        ),
    ),
    (
        "culture",
        "demo-editor-culture@example.com",
        "editor-culture-note",
        _content(
            "From the culture desk",
            "Openings the desk will cover.",
            "The culture desk has three openings on the week's list.",
            "A preview runs only after the venue confirms the time.",
        ),
    ),
)
_WRITER_STORIES = (
    (
        "economy",
        "demo-writer-economy@example.com",
        "writer-economy-note",
        _content(
            "Shops keep the later closing time",
            "Evening hours stay in place.",
            "Corner shops on the market street will keep the later closing time.",
            "The board posted the hours on the stall doors.",
        ),
    ),
    (
        "science",
        "demo-writer-science@example.com",
        "writer-science-note",
        _content(
            "Harbor gauge is back in service",
            "The tide reading resumed this morning.",
            "Technicians put the harbor gauge back in service before dawn.",
            "The first reading of the day matched the dock log.",
        ),
    ),
    (
        "culture",
        "demo-writer-culture@example.com",
        "writer-culture-note",
        _content(
            "Poetry night names six readers",
            "The hall holds the reading on Thursday.",
            "The poetry night named six readers for Thursday.",
            "The hall opens its doors an hour before the first poem.",
        ),
    ),
)


async def _missing(db: AsyncSession, slug: str) -> bool:
    found = await db.scalar(select(ArticleLocalization.id).where(ArticleLocalization.slug == slug))
    return found is None


async def _file(
    articles: ArticleService,
    writer: Principal,
    author_id: uuid.UUID,
    section_id: uuid.UUID,
    slug: str,
    content: RevisionContent,
) -> tuple[uuid.UUID, int]:
    created = await articles.create(
        writer,
        ArticleCreate(
            section_id=section_id,
            article_type=ArticleType.NEWS,
            author_ids=[author_id],
            locale="en",
            slug=slug,
            content=content,
        ),
    )
    loc = created.localizations[0]
    return loc.id, loc.lock_version


async def _move(
    articles: ArticleService,
    actor: Principal,
    localization_id: uuid.UUID,
    lock: int,
    action: ArticleAction,
    **extra: object,
) -> int:
    result = await articles.transition(
        actor,
        localization_id,
        TransitionRequest(action=action, lock_version=lock, **extra),  # type: ignore[arg-type]
    )
    return result.lock_version


async def _to_copy(
    articles: ArticleService,
    writer: Principal,
    editor: Principal,
    localization_id: uuid.UUID,
    lock: int,
) -> int:
    lock = await _move(articles, writer, localization_id, lock, ArticleAction.SUBMIT)
    return await _move(articles, editor, localization_id, lock, ArticleAction.SEND_TO_COPY)


async def _to_approved(
    articles: ArticleService,
    writer: Principal,
    editor: Principal,
    copy_editor: Principal,
    localization_id: uuid.UUID,
    lock: int,
) -> int:
    lock = await _to_copy(articles, writer, editor, localization_id, lock)
    return await _move(articles, copy_editor, localization_id, lock, ArticleAction.FINISH_COPY)


async def _to_published(
    articles: ArticleService,
    writer: Principal,
    editor: Principal,
    copy_editor: Principal,
    localization_id: uuid.UUID,
    lock: int,
) -> int:
    lock = await _to_approved(articles, writer, editor, copy_editor, localization_id, lock)
    return await _move(articles, editor, localization_id, lock, ArticleAction.PUBLISH)


async def _publish_own(
    articles: ArticleService,
    editor: Principal,
    copy_editor: Principal,
    author_id: uuid.UUID,
    section_id: uuid.UUID,
    slug: str,
    content: RevisionContent,
) -> None:
    loc_id, lock = await _file(articles, editor, author_id, section_id, slug, content)
    lock = await _move(articles, editor, loc_id, lock, ArticleAction.SUBMIT)
    lock = await _move(articles, editor, loc_id, lock, ArticleAction.SEND_TO_COPY)
    lock = await _move(articles, copy_editor, loc_id, lock, ArticleAction.FINISH_COPY)
    await _move(articles, editor, loc_id, lock, ArticleAction.PUBLISH)


async def _seed_reader_notes(db: AsyncSession, articles: ArticleService) -> None:
    repo = UserRepository(db)
    for email, slug, body in _COMMENTS:
        await _comment(db, email, slug, body)
    for email, slug in _BOOKMARKS:
        user = await repo.get_by_email(email)
        article_id = await db.scalar(
            select(ArticleLocalization.article_id).where(ArticleLocalization.slug == slug)
        )
        if user is None or article_id is None:
            continue
        await articles.bookmark(user.id, article_id)


async def _comment(db: AsyncSession, email: str, slug: str, body: str) -> None:
    user = await UserRepository(db).get_by_email(email)
    localization_id = await db.scalar(
        select(ArticleLocalization.id).where(ArticleLocalization.slug == slug)
    )
    if user is None or localization_id is None:
        return
    existing = await db.scalar(
        select(Comment.id).where(
            Comment.user_id == user.id,
            Comment.localization_id == localization_id,
            Comment.body == body,
        )
    )
    if existing is not None:
        return
    await CommentService(db).add(await _principal(db, email), localization_id, body)
