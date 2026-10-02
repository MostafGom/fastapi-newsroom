from dataclasses import dataclass
from enum import StrEnum


class Perm(StrEnum):
    ARTICLE_CREATE = "article.create"
    ARTICLE_READ = "article.read"
    ARTICLE_EDIT_OWN = "article.edit_own"
    ARTICLE_EDIT = "article.edit"
    ARTICLE_SUBMIT = "article.submit"
    ARTICLE_COPY = "article.copy"
    ARTICLE_REVIEW = "article.review"
    ARTICLE_CLEAR_LEGAL = "article.clear_legal"
    ARTICLE_PUBLISH = "article.publish"
    ARTICLE_UNPUBLISH = "article.unpublish"
    ARTICLE_ARCHIVE = "article.archive"
    ARTICLE_DELETE_DRAFT = "article.delete_draft"
    ARTICLE_RESTORE_REVISION = "article.restore_revision"
    ARTICLE_CORRECT = "article.correct"
    ARTICLE_PURGE = "article.purge"
    SECTION_MANAGE = "section.manage"
    TAG_MANAGE = "tag.manage"
    MEDIA_UPLOAD = "media.upload"
    MEDIA_MANAGE = "media.manage"
    LOCALE_MANAGE = "locale.manage"
    USER_READ = "user.read"
    USER_MANAGE = "user.manage"
    ROLE_ASSIGN = "role.assign"
    ROLE_MANAGE = "role.manage"
    AUDIT_READ = "audit.read"
    SETTINGS_MANAGE = "settings.manage"
    PAGE_MANAGE = "page.manage"


PERMISSION_DESCRIPTIONS: dict[Perm, str] = {
    Perm.ARTICLE_CREATE: "Create articles and localizations",
    Perm.ARTICLE_READ: "View any article in scope in the dashboard",
    Perm.ARTICLE_EDIT_OWN: "Edit own articles in draft/changes_requested; propose updates to own "
    "published articles",
    Perm.ARTICLE_EDIT: "Edit any article in scope in any non-archived state",
    Perm.ARTICLE_SUBMIT: "Submit articles for review",
    Perm.ARTICLE_COPY: "Copy-edit, return to the writer, and sign off copy",
    Perm.ARTICLE_REVIEW: "Accept a story, send it to copy, request changes, or skip copy",
    Perm.ARTICLE_CLEAR_LEGAL: "Record that counsel has cleared a story held for legal review",
    Perm.ARTICLE_PUBLISH: "Publish, schedule, publish updates, republish",
    Perm.ARTICLE_UNPUBLISH: "Take down published articles",
    Perm.ARTICLE_ARCHIVE: "Archive and unarchive articles",
    Perm.ARTICLE_DELETE_DRAFT: "Soft-delete never-published localizations",
    Perm.ARTICLE_RESTORE_REVISION: "Restore an older revision as the working copy",
    Perm.ARTICLE_CORRECT: "Add public correction notes",
    Perm.ARTICLE_PURGE: "Legal hard-removal of content",
    Perm.SECTION_MANAGE: "Manage sections",
    Perm.TAG_MANAGE: "Manage tags",
    Perm.MEDIA_UPLOAD: "Upload media",
    Perm.MEDIA_MANAGE: "Edit or delete any media",
    Perm.LOCALE_MANAGE: "Manage locales",
    Perm.USER_READ: "View user accounts",
    Perm.USER_MANAGE: "Create and suspend user accounts below own rank",
    Perm.ROLE_ASSIGN: "Grant and revoke roles below own rank",
    Perm.ROLE_MANAGE: "Define roles and their permissions",
    Perm.AUDIT_READ: "Read the audit log",
    Perm.SETTINGS_MANAGE: "Manage system settings",
    Perm.PAGE_MANAGE: "Create and publish site pages",
}


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    key: str
    name: str
    rank: int
    permissions: frozenset[Perm]
    description: str


_WRITER = frozenset(
    {
        Perm.ARTICLE_CREATE,
        Perm.ARTICLE_EDIT_OWN,
        Perm.ARTICLE_SUBMIT,
        Perm.ARTICLE_DELETE_DRAFT,
        Perm.MEDIA_UPLOAD,
    }
)
_COPY_EDITOR = frozenset(
    {
        Perm.ARTICLE_READ,
        Perm.ARTICLE_EDIT,
        Perm.ARTICLE_COPY,
        Perm.MEDIA_UPLOAD,
    }
)
_EDITOR = (
    _WRITER
    | _COPY_EDITOR
    | {
        Perm.ARTICLE_REVIEW,
        Perm.ARTICLE_CLEAR_LEGAL,
        Perm.ARTICLE_PUBLISH,
        Perm.ARTICLE_UNPUBLISH,
        Perm.ARTICLE_RESTORE_REVISION,
        Perm.ARTICLE_CORRECT,
        Perm.TAG_MANAGE,
        Perm.MEDIA_MANAGE,
    }
)
_ADMIN = _EDITOR | {
    Perm.ARTICLE_ARCHIVE,
    Perm.SECTION_MANAGE,
    Perm.LOCALE_MANAGE,
    Perm.USER_READ,
    Perm.USER_MANAGE,
    Perm.ROLE_ASSIGN,
    Perm.AUDIT_READ,
    Perm.PAGE_MANAGE,
}
_SUPER_ADMIN = frozenset(Perm)

SUPER_ADMIN_ROLE = "super_admin"

SYSTEM_ROLES: tuple[RoleDefinition, ...] = (
    RoleDefinition("writer", "Writer", 10, _WRITER, "Drafts and submits articles."),
    RoleDefinition(
        "copy_editor",
        "Copy editor",
        15,
        _COPY_EDITOR,
        "Line-edits language, headlines and style. Does not publish.",
    ),
    RoleDefinition(
        "editor",
        "Editor",
        20,
        _EDITOR,
        "Desk editor: news judgment, legal clearance, publishing. Usually section-scoped.",
    ),
    RoleDefinition("admin", "Admin", 30, _ADMIN, "Runs the newsroom: taxonomy, staff, roles."),
    RoleDefinition(
        SUPER_ADMIN_ROLE, "Super admin", 100, _SUPER_ADMIN, "Full control, including admins."
    ),
)
