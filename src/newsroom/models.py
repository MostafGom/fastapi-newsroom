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
from newsroom.core.models import Base
from newsroom.locales.models import Locale
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
    "Correction",
    "Locale",
    "Permission",
    "ReaderProfile",
    "Role",
    "Section",
    "SectionTranslation",
    "SlugRedirect",
    "StaffProfile",
    "Tag",
    "TagTranslation",
    "User",
    "UserRole",
    "role_permissions",
]
