"""Import every ORM model so ``Base.metadata`` is complete (Alembic, tests)."""

from newsroom.articles.models import (
    Article,
    ArticleAuthor,
    ArticleLocalization,
    ArticleRevision,
    ArticleTag,
    Author,
    AuthorTranslation,
    Bookmark,
    Correction,
    SlugRedirect,
)
from newsroom.audit.models import AuditEvent
from newsroom.auth.models import AuthSession
from newsroom.authz.models import Permission, Role, UserRole, role_permissions
from newsroom.comments.models import Comment
from newsroom.core.models import Base
from newsroom.homepage.models import HomepageSlot
from newsroom.locales.models import Locale
from newsroom.media.models import MediaAsset, MediaTranslation
from newsroom.newsletters.models import NewsletterDelivery, NewsletterIssue
from newsroom.search.models import SearchDocument
from newsroom.settings.models import SiteSettings
from newsroom.taxonomy.models import Section, SectionTranslation, Tag, TagTranslation
from newsroom.users.models import ReaderProfile, StaffProfile, User

__all__ = [
    "Article",
    "ArticleAuthor",
    "ArticleLocalization",
    "ArticleRevision",
    "ArticleTag",
    "AuditEvent",
    "AuthSession",
    "Author",
    "AuthorTranslation",
    "Base",
    "Bookmark",
    "Comment",
    "Correction",
    "HomepageSlot",
    "Locale",
    "MediaAsset",
    "MediaTranslation",
    "NewsletterDelivery",
    "NewsletterIssue",
    "Permission",
    "ReaderProfile",
    "Role",
    "SearchDocument",
    "Section",
    "SectionTranslation",
    "SiteSettings",
    "SlugRedirect",
    "StaffProfile",
    "Tag",
    "TagTranslation",
    "User",
    "UserRole",
    "role_permissions",
]
