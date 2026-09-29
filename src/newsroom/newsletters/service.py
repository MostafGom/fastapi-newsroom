import asyncio
import smtplib
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from newsroom.articles.service import ArticleService
from newsroom.audit.service import record_event
from newsroom.auth.service import utcnow
from newsroom.core.config import Settings, get_settings
from newsroom.core.i18n import translate
from newsroom.core.schemas import PageParams
from newsroom.homepage.service import HomepageService
from newsroom.newsletters.models import NewsletterDelivery, NewsletterIssue
from newsroom.users.models import ReaderProfile, User, UserStatus


class NewsletterService:
    """One briefing per locale per day. Rows are the record of who should receive it."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def send_due(
        self,
        edition: date | None = None,
        *,
        deliver: Callable[[str, str, str], None] | None = None,
    ) -> int:
        edition = edition or datetime.now(UTC).date()
        settings = get_settings()
        delivered = 0
        for locale in settings.supported_locales:
            delivered += await self._issue(locale, edition, settings, deliver)
        return delivered

    async def _issue(
        self,
        locale: str,
        edition: date,
        settings: Settings,
        deliver: Callable[[str, str, str], None] | None,
    ) -> int:
        existing = await self.db.scalar(
            select(NewsletterIssue.id).where(
                NewsletterIssue.locale == locale,
                NewsletterIssue.edition_date == edition,
            )
        )
        if existing is not None:
            return 0
        curated = await HomepageService(self.db).public_stories(locale)
        if curated is None:
            page = await ArticleService(self.db).list_public(
                locale, PageParams(limit=5, cursor=None), section_slug=None, tag_slug=None
            )
            stories = page.items
        else:
            stories = [item.summary for item in curated[:5]]
        if not stories:
            return 0
        readers = list(
            (
                await self.db.scalars(
                    select(User)
                    .join(ReaderProfile, ReaderProfile.user_id == User.id)
                    .where(
                        ReaderProfile.newsletter_opt_in.is_(True),
                        ReaderProfile.preferred_locale == locale,
                        User.status == UserStatus.ACTIVE,
                    )
                    .options(selectinload(User.reader_profile))
                )
            ).all()
        )
        if not readers:
            return 0
        subject = f"{settings.app_name} {edition.isoformat()}"
        body = _briefing(settings.public_base_url, locale, stories)
        recipients = await _reach(readers, subject, body, settings, deliver)
        if not recipients:
            return 0
        issue_id = uuid.uuid7()
        self.db.add(
            NewsletterIssue(
                id=issue_id,
                locale=locale,
                edition_date=edition,
                subject=subject,
                story_slugs=[item.slug for item in stories],
                created_at=utcnow(),
            )
        )
        await self.db.flush()
        for user in recipients:
            self.db.add(NewsletterDelivery(issue_id=issue_id, user_id=user.id, created_at=utcnow()))
        record_event(
            self.db,
            actor_id=None,
            action="newsletter.issued",
            entity_type="newsletter_issue",
            entity_id=issue_id,
            after={"locale": locale, "recipients": len(recipients)},
        )
        await self.db.commit()
        return len(recipients)


def _briefing(base_url: str, locale: str, stories) -> str:
    lines = [translate(locale, "site.title"), ""]
    root = base_url.rstrip("/")
    for story in stories:
        lines.append(story.title)
        lines.append(f"{root}/{locale}/article/{story.slug}")
        lines.append("")
    return "\n".join(lines).strip()


async def _reach(readers, subject: str, body: str, settings: Settings, deliver) -> list:
    if deliver is None and not settings.smtp_host:
        return list(readers)
    reached = []
    for user in readers:
        try:
            if deliver is not None:
                deliver(user.email, subject, body)
            else:
                await asyncio.to_thread(_smtp, user.email, subject, body, settings)
        except OSError, smtplib.SMTPException:
            continue
        reached.append(user)
    return reached


def _smtp(to: str, subject: str, body: str, settings: Settings) -> None:
    if not settings.smtp_host:
        return
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_username or "newsroom@localhost"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_port != 25:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password is not None:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)
