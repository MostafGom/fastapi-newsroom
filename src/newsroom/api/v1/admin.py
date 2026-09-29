import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from newsroom.articles.authors import AuthorCreate, AuthorOut, AuthorService
from newsroom.articles.schemas import (
    ArticleAdminOut,
    ArticleCreate,
    ArticleUpdate,
    CorrectionCreate,
    CorrectionOut,
    HistoryEntryOut,
    LocalizationCreate,
    LocalizationOut,
    ReasonRequest,
    RestoreRequest,
    RevisionCreate,
    RevisionDiffOut,
    RevisionOut,
    RevisionSummaryOut,
    SlugChange,
    TransitionRequest,
)
from newsroom.articles.service import ArticleService
from newsroom.articles.workflow import ArticleStatus
from newsroom.audit.schemas import AuditEventOut
from newsroom.audit.service import AuditService
from newsroom.auth.dependencies import csrf_protect
from newsroom.authz.dependencies import CurrentStaff, require_permission, require_staff
from newsroom.authz.permissions import Perm
from newsroom.core.db import DbSession
from newsroom.core.schemas import PROBLEM_RESPONSES, Page, PageParams, page_params
from newsroom.locales.service import LocaleAdminOut, LocaleCreate, LocaleService
from newsroom.settings.service import SettingsService, SiteSettingsOut, SiteSettingsUpdate
from newsroom.taxonomy.schemas import (
    SectionAdminOut,
    SectionCreate,
    SectionUpdate,
    TagAdminOut,
    TagCreate,
    TagMerge,
)
from newsroom.taxonomy.service import TaxonomyService
from newsroom.users.models import UserKind, UserStatus
from newsroom.users.schemas import (
    RoleCreate,
    RoleGrantCreate,
    RoleOut,
    RoleUpdate,
    StaffCreate,
    UserOut,
    UserRoleOut,
    UserUpdate,
)
from newsroom.users.service import UserService

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    responses=PROBLEM_RESPONSES,
    dependencies=[Depends(require_staff), Depends(csrf_protect)],
)

Paging = Annotated[PageParams, Depends(page_params)]


def can(perm: Perm) -> list:
    return [Depends(require_permission(perm))]


# ---- Articles -------------------------------------------------------------------------------
# Route-level checks are coarse ("holds the permission in any scope"). Services apply section
# scope, ownership and state policies once the entity is loaded.


@router.get("/articles", response_model=Page[ArticleAdminOut], tags=["articles"])
async def list_articles(
    staff: CurrentStaff,
    db: DbSession,
    paging: Paging,
    status_: Annotated[ArticleStatus | None, Query(alias="status")] = None,
    locale: str | None = None,
    section_id: uuid.UUID | None = None,
    author_id: uuid.UUID | None = None,
) -> Page[ArticleAdminOut]:
    del author_id
    return await ArticleService(db).list_admin(
        staff, paging, status=status_, locale=locale, section_id=section_id
    )


@router.post(
    "/articles",
    response_model=ArticleAdminOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.ARTICLE_CREATE),
    tags=["articles"],
)
async def create_article(
    payload: ArticleCreate, staff: CurrentStaff, db: DbSession
) -> ArticleAdminOut:
    return await ArticleService(db).create(staff, payload)


@router.get("/articles/{article_id}", response_model=ArticleAdminOut, tags=["articles"])
async def get_article(article_id: uuid.UUID, staff: CurrentStaff, db: DbSession) -> ArticleAdminOut:
    return await ArticleService(db).get_admin(staff, article_id)


@router.patch("/articles/{article_id}", response_model=ArticleAdminOut, tags=["articles"])
async def update_article(
    article_id: uuid.UUID, payload: ArticleUpdate, staff: CurrentStaff, db: DbSession
) -> ArticleAdminOut:
    return await ArticleService(db).update_article(staff, article_id, payload)


@router.post(
    "/articles/{article_id}/localizations",
    response_model=LocalizationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.ARTICLE_CREATE),
    tags=["articles"],
)
async def create_localization(
    article_id: uuid.UUID, payload: LocalizationCreate, staff: CurrentStaff, db: DbSession
) -> LocalizationOut:
    return await ArticleService(db).add_localization(staff, article_id, payload)


@router.get("/localizations/{localization_id}", response_model=LocalizationOut, tags=["articles"])
async def get_localization(
    localization_id: uuid.UUID, staff: CurrentStaff, db: DbSession
) -> LocalizationOut:
    return await ArticleService(db).get_localization(staff, localization_id)


@router.delete(
    "/localizations/{localization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=can(Perm.ARTICLE_DELETE_DRAFT),
    tags=["articles"],
)
async def delete_localization(
    localization_id: uuid.UUID, staff: CurrentStaff, db: DbSession
) -> None:
    await ArticleService(db).delete_localization(staff, localization_id)


@router.get(
    "/localizations/{localization_id}/revisions",
    response_model=Page[RevisionSummaryOut],
    tags=["revisions"],
)
async def list_revisions(
    localization_id: uuid.UUID, staff: CurrentStaff, paging: Paging, db: DbSession
) -> Page[RevisionSummaryOut]:
    return await ArticleService(db).list_revisions(staff, localization_id, paging)


@router.post(
    "/localizations/{localization_id}/revisions",
    response_model=RevisionOut,
    status_code=status.HTTP_201_CREATED,
    tags=["revisions"],
    responses={409: {"description": "base_revision_id is stale (code=revision_conflict)"}},
)
async def save_revision(
    localization_id: uuid.UUID, payload: RevisionCreate, staff: CurrentStaff, db: DbSession
) -> RevisionOut:
    return await ArticleService(db).save_revision(staff, localization_id, payload)


@router.get(
    "/localizations/{localization_id}/revisions/{revision_id}",
    response_model=RevisionOut,
    tags=["revisions"],
)
async def get_revision(
    localization_id: uuid.UUID, revision_id: uuid.UUID, staff: CurrentStaff, db: DbSession
) -> RevisionOut:
    return await ArticleService(db).get_revision(staff, localization_id, revision_id)


@router.get(
    "/localizations/{localization_id}/revisions/{from_id}/diff/{to_id}",
    response_model=RevisionDiffOut,
    tags=["revisions"],
)
async def diff_revisions(
    localization_id: uuid.UUID,
    from_id: uuid.UUID,
    to_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
) -> RevisionDiffOut:
    return await ArticleService(db).diff_revisions(staff, localization_id, from_id, to_id)


@router.post(
    "/localizations/{localization_id}/revisions/{revision_id}/restore",
    response_model=RevisionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.ARTICLE_RESTORE_REVISION),
    tags=["revisions"],
)
async def restore_revision(
    localization_id: uuid.UUID,
    revision_id: uuid.UUID,
    payload: RestoreRequest,
    staff: CurrentStaff,
    db: DbSession,
) -> RevisionOut:
    return await ArticleService(db).restore_revision(staff, localization_id, revision_id, payload)


@router.post(
    "/localizations/{localization_id}/transitions",
    response_model=LocalizationOut,
    tags=["workflow"],
    responses={409: {"description": "Illegal transition or stale lock_version"}},
)
async def transition_localization(
    localization_id: uuid.UUID, payload: TransitionRequest, staff: CurrentStaff, db: DbSession
) -> LocalizationOut:
    return await ArticleService(db).transition(staff, localization_id, payload)


@router.get(
    "/localizations/{localization_id}/history",
    response_model=list[HistoryEntryOut],
    tags=["workflow"],
)
async def localization_history(
    localization_id: uuid.UUID, staff: CurrentStaff, db: DbSession
) -> list[HistoryEntryOut]:
    return await ArticleService(db).history(staff, localization_id)


@router.post("/localizations/{localization_id}/legal-hold", status_code=status.HTTP_204_NO_CONTENT)
async def set_legal_hold(
    localization_id: uuid.UUID, payload: ReasonRequest, staff: CurrentStaff, db: DbSession
) -> None:
    await ArticleService(db).set_legal_hold(staff, localization_id, payload.reason)


@router.post(
    "/localizations/{localization_id}/legal-hold/clear", status_code=status.HTTP_204_NO_CONTENT
)
async def clear_legal_hold(
    localization_id: uuid.UUID, payload: ReasonRequest, staff: CurrentStaff, db: DbSession
) -> None:
    await ArticleService(db).clear_legal_hold(staff, localization_id, payload.reason)


@router.post("/localizations/{localization_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_localization(
    localization_id: uuid.UUID, payload: ReasonRequest, staff: CurrentStaff, db: DbSession
) -> None:
    await ArticleService(db).purge(staff, localization_id, payload.reason)


@router.post(
    "/localizations/{localization_id}/corrections",
    response_model=CorrectionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.ARTICLE_CORRECT),
    tags=["workflow"],
)
async def add_correction(
    localization_id: uuid.UUID, payload: CorrectionCreate, staff: CurrentStaff, db: DbSession
) -> CorrectionOut:
    return await ArticleService(db).add_correction(staff, localization_id, payload)


@router.post(
    "/localizations/{localization_id}/slug",
    response_model=LocalizationOut,
    tags=["articles"],
)
async def change_slug(
    localization_id: uuid.UUID, payload: SlugChange, staff: CurrentStaff, db: DbSession
) -> LocalizationOut:
    return await ArticleService(db).change_slug(staff, localization_id, payload)


# ---- Taxonomy -------------------------------------------------------------------------------


@router.get("/sections", response_model=list[SectionAdminOut], tags=["taxonomy"])
async def list_sections(staff: CurrentStaff, db: DbSession) -> list[SectionAdminOut]:
    del staff
    return await TaxonomyService(db).list_admin_sections()


@router.post(
    "/sections",
    response_model=SectionAdminOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.SECTION_MANAGE),
    tags=["taxonomy"],
)
async def create_section(payload: SectionCreate, db: DbSession) -> SectionAdminOut:
    return await TaxonomyService(db).create_section(payload)


@router.patch(
    "/sections/{section_id}",
    response_model=SectionAdminOut,
    dependencies=can(Perm.SECTION_MANAGE),
    tags=["taxonomy"],
)
async def update_section(
    section_id: uuid.UUID, payload: SectionUpdate, db: DbSession
) -> SectionAdminOut:
    return await TaxonomyService(db).update_section(section_id, payload)


@router.get("/tags", response_model=Page[TagAdminOut], tags=["taxonomy"])
async def list_tags(
    staff: CurrentStaff, db: DbSession, paging: Paging, q: str | None = None
) -> Page[TagAdminOut]:
    del staff
    return await TaxonomyService(db).list_tags(paging, q)


@router.post(
    "/tags",
    response_model=TagAdminOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.TAG_MANAGE),
    tags=["taxonomy"],
)
async def create_tag(payload: TagCreate, db: DbSession) -> TagAdminOut:
    return await TaxonomyService(db).create_tag(payload)


@router.post(
    "/tags/merge",
    response_model=TagAdminOut,
    dependencies=can(Perm.TAG_MANAGE),
    tags=["taxonomy"],
)
async def merge_tags(payload: TagMerge, staff: CurrentStaff, db: DbSession) -> TagAdminOut:
    return await TaxonomyService(db).merge_tags(staff, payload.source_id, payload.target_id)


# ---- Users and roles ------------------------------------------------------------------------


@router.get(
    "/users", response_model=Page[UserOut], dependencies=can(Perm.USER_READ), tags=["users"]
)
async def list_users(
    db: DbSession,
    paging: Paging,
    kind: UserKind | None = None,
    status_: Annotated[UserStatus | None, Query(alias="status")] = None,
    q: str | None = None,
) -> Page[UserOut]:
    return await UserService(db).list_users(paging, kind=kind, status=status_, q=q)


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.USER_MANAGE),
    tags=["users"],
)
async def create_staff_user(payload: StaffCreate, staff: CurrentStaff, db: DbSession) -> UserOut:
    return await UserService(db).create_staff_account(staff, payload)


@router.get(
    "/users/{user_id}", response_model=UserOut, dependencies=can(Perm.USER_READ), tags=["users"]
)
async def get_user(user_id: uuid.UUID, db: DbSession) -> UserOut:
    return await UserService(db).get_user(user_id)


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    dependencies=can(Perm.USER_MANAGE),
    tags=["users"],
)
async def update_user(
    user_id: uuid.UUID, payload: UserUpdate, staff: CurrentStaff, db: DbSession
) -> UserOut:
    return await UserService(db).update_user(staff, user_id, payload)


@router.post(
    "/users/{user_id}/roles",
    response_model=UserRoleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.ROLE_ASSIGN),
    tags=["users"],
)
async def grant_role(
    user_id: uuid.UUID, payload: RoleGrantCreate, staff: CurrentStaff, db: DbSession
) -> UserRoleOut:
    return await UserService(db).grant_role(staff, user_id, payload)


@router.delete(
    "/users/{user_id}/roles/{user_role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=can(Perm.ROLE_ASSIGN),
    tags=["users"],
)
async def revoke_role(
    user_id: uuid.UUID, user_role_id: uuid.UUID, staff: CurrentStaff, db: DbSession
) -> None:
    await UserService(db).revoke_role(staff, user_id, user_role_id)


@router.get(
    "/roles", response_model=list[RoleOut], dependencies=can(Perm.USER_READ), tags=["users"]
)
async def list_roles(db: DbSession) -> list[RoleOut]:
    return await UserService(db).list_roles()


@router.post(
    "/roles",
    response_model=RoleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.ROLE_MANAGE),
    tags=["users"],
)
async def create_role(payload: RoleCreate, staff: CurrentStaff, db: DbSession) -> RoleOut:
    return await UserService(db).create_role(staff, payload)


@router.patch(
    "/roles/{role_id}",
    response_model=RoleOut,
    dependencies=can(Perm.ROLE_MANAGE),
    tags=["users"],
)
async def update_role(
    role_id: uuid.UUID, payload: RoleUpdate, staff: CurrentStaff, db: DbSession
) -> RoleOut:
    return await UserService(db).update_role(staff, role_id, payload)


@router.get("/authors", response_model=list[AuthorOut], tags=["authors"])
async def list_authors(staff: CurrentStaff, db: DbSession) -> list[AuthorOut]:
    del staff
    return await AuthorService(db).list_bylines()


@router.post(
    "/authors",
    response_model=AuthorOut,
    status_code=status.HTTP_201_CREATED,
    tags=["authors"],
)
async def create_author(payload: AuthorCreate, staff: CurrentStaff, db: DbSession) -> AuthorOut:
    return await AuthorService(db).create(staff, payload)


@router.delete("/authors/{author_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["authors"])
async def delete_author(author_id: uuid.UUID, staff: CurrentStaff, db: DbSession) -> None:
    await AuthorService(db).delete(staff, author_id)


@router.get(
    "/locales",
    response_model=list[LocaleAdminOut],
    dependencies=can(Perm.LOCALE_MANAGE),
    tags=["locales"],
)
async def list_locales_admin(db: DbSession) -> list[LocaleAdminOut]:
    return await LocaleService(db).list_all()


@router.post(
    "/locales",
    response_model=LocaleAdminOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=can(Perm.LOCALE_MANAGE),
    tags=["locales"],
)
async def create_locale(
    payload: LocaleCreate, staff: CurrentStaff, db: DbSession
) -> LocaleAdminOut:
    return await LocaleService(db).create(staff, payload)


@router.post(
    "/locales/{code}/default",
    response_model=LocaleAdminOut,
    dependencies=can(Perm.LOCALE_MANAGE),
    tags=["locales"],
)
async def default_locale(code: str, staff: CurrentStaff, db: DbSession) -> LocaleAdminOut:
    return await LocaleService(db).set_default(staff, code)


@router.post(
    "/locales/{code}/enabled",
    response_model=LocaleAdminOut,
    dependencies=can(Perm.LOCALE_MANAGE),
    tags=["locales"],
)
async def set_locale_enabled(
    code: str, staff: CurrentStaff, db: DbSession, enabled: bool = True
) -> LocaleAdminOut:
    return await LocaleService(db).set_enabled(staff, code, enabled)


@router.get(
    "/settings",
    response_model=SiteSettingsOut,
    dependencies=can(Perm.SETTINGS_MANAGE),
    tags=["settings"],
)
async def read_settings(db: DbSession) -> SiteSettingsOut:
    return await SettingsService(db).get()


@router.put(
    "/settings",
    response_model=SiteSettingsOut,
    dependencies=can(Perm.SETTINGS_MANAGE),
    tags=["settings"],
)
async def write_settings(
    payload: SiteSettingsUpdate, staff: CurrentStaff, db: DbSession
) -> SiteSettingsOut:
    return await SettingsService(db).update(staff, payload)


# ---- Audit ----------------------------------------------------------------------------------


@router.get(
    "/audit-events",
    response_model=Page[AuditEventOut],
    dependencies=can(Perm.AUDIT_READ),
    tags=["audit"],
)
async def list_audit_events(
    db: DbSession,
    paging: Paging,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Page[AuditEventOut]:
    return await AuditService(db).list_events(
        paging,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        since=since,
        until=until,
    )
