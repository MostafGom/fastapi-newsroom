"""Staff desk: file a story, save revisions, and move it through the workflow."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import select

from newsroom.articles.authors import AuthorService
from newsroom.articles.body import InvalidBody
from newsroom.articles.schemas import (
    ArticleCreate,
    ArticleType,
    CorrectionCreate,
    LocalizationCreate,
    RestoreRequest,
    RevisionContent,
    RevisionCreate,
    SlugChange,
    TransitionRequest,
)
from newsroom.articles.service import ArticleService, edition_window
from newsroom.articles.workflow import (
    TRANSITIONS,
    ArticleAction,
    ArticleStatus,
    CorrectionKind,
    TakedownReason,
)
from newsroom.auth.dependencies import csrf_protect_web
from newsroom.authz.dependencies import CurrentStaff
from newsroom.authz.permissions import Perm
from newsroom.comments.service import CommentService
from newsroom.core.db import DbSession
from newsroom.core.errors import AppError, PermissionDenied
from newsroom.core.schemas import PageParams
from newsroom.taxonomy.schemas import SectionAdminOut, TagAdminOut
from newsroom.taxonomy.service import TaxonomyService
from newsroom.users.models import User, UserKind
from newsroom.users.service import UserService
from newsroom.web.paging import PageQuery, is_fragment, listing_params, pager_context
from newsroom.web.templating import _request_locale, templates

_STORY_PAGE = 50

router = APIRouter(
    prefix="/admin", dependencies=[Depends(csrf_protect_web)], include_in_schema=False
)

EMPTY_DOC = {"type": "doc", "content": [{"type": "paragraph"}]}


@dataclass(frozen=True, slots=True)
class StoryRow:
    localization_id: uuid.UUID
    title: str
    locale: str
    slug: str
    status: str
    section: str
    bylines: tuple[str, ...]
    editor: str | None
    updated_at: datetime
    legal_hold: bool


def _direction(locale: str) -> str:
    return "rtl" if locale == "ar" else "ltr"


def _label(section: SectionAdminOut, locale: str) -> str:
    row = next((item for item in section.translations if item.locale == locale), None)
    if row is None and section.translations:
        row = section.translations[0]
    return row.name if row else section.key


def _tag_label(tag: TagAdminOut, locale: str) -> str:
    row = next((item for item in tag.translations if item.locale == locale), None)
    if row is None and tag.translations:
        row = tag.translations[0]
    return row.name if row else tag.key


def _parse_body(raw: str) -> dict:
    try:
        document = json.loads(raw) if raw.strip() else EMPTY_DOC
    except json.JSONDecodeError as exc:
        raise InvalidBody("Body is not valid JSON") from exc
    if not isinstance(document, dict):
        raise InvalidBody("Body is not a document")
    return document


def _content(title: str, subtitle: str, excerpt: str, body: str) -> RevisionContent:
    return RevisionContent(
        title=title.strip(),
        subtitle=subtitle.strip() or None,
        excerpt=excerpt.strip() or None,
        body=_parse_body(body),
    )


def _ids(raw: list[str]) -> list[uuid.UUID]:
    return [uuid.UUID(item) for item in raw if item]


def _when(raw: str) -> datetime | None:
    text = raw.strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _can_change_slug(staff: CurrentStaff, article, story) -> bool:
    if story.status is ArticleStatus.ARCHIVED:
        return False
    section_id = article.section_id
    if story.published_at is not None:
        return staff.grants.has(Perm.ARTICLE_EDIT, section_id=section_id)
    if staff.grants.has(Perm.ARTICLE_EDIT, section_id=section_id):
        return True
    return article.created_by == staff.user.id and staff.grants.has_anywhere(Perm.ARTICLE_EDIT_OWN)


def _visible_actions(staff: CurrentStaff, section_id: uuid.UUID, created_by: uuid.UUID, actions):
    """Same ownership rule as ArticleService: a writer acts only on their own draft."""
    visible = []
    can_edit = staff.grants.has(Perm.ARTICLE_EDIT, section_id=section_id)
    for action in actions:
        edge = TRANSITIONS[action]
        if edge.owner_may_act and not can_edit:
            if created_by == staff.user.id and staff.grants.has_anywhere(edge.permission):
                visible.append(action)
            continue
        if staff.grants.has(edge.permission, section_id=section_id):
            visible.append(action)
    return visible


@dataclass(frozen=True, slots=True)
class DeskStep:
    value: str
    requires_reason: bool
    needs_schedule: bool


_ACTION_GROUPS: tuple[tuple[str, tuple[ArticleAction, ...]], ...] = (
    (
        "desk",
        (
            ArticleAction.SUBMIT,
            ArticleAction.WITHDRAW,
            ArticleAction.SEND_TO_COPY,
            ArticleAction.RETURN_TO_WRITER,
            ArticleAction.FINISH_COPY,
            ArticleAction.REQUEST_CHANGES,
            ArticleAction.APPROVE,
        ),
    ),
    (
        "publish",
        (
            ArticleAction.SCHEDULE,
            ArticleAction.CANCEL_SCHEDULE,
            ArticleAction.PUBLISH,
            ArticleAction.PUBLISH_UPDATE,
            ArticleAction.REPUBLISH,
        ),
    ),
    (
        "live",
        (ArticleAction.ARCHIVE, ArticleAction.UNARCHIVE),
    ),
    ("stop", (ArticleAction.KILL, ArticleAction.DELETE)),
)


def _group_actions(actions: list[ArticleAction]) -> list[dict]:
    """Bucket the steps this person can take. Empty groups stay off the page."""
    allowed = set(actions)
    grouped: list[dict] = []
    for key, members in _ACTION_GROUPS:
        steps = [
            DeskStep(
                value=action.value,
                requires_reason=TRANSITIONS[action].requires_reason,
                needs_schedule=action is ArticleAction.SCHEDULE,
            )
            for action in members
            if action in allowed
        ]
        if steps:
            grouped.append({"key": key, "steps": steps})
    return grouped


async def _desk_choices(db: DbSession, locale: str) -> tuple[list[dict], list[dict]]:
    sections = await TaxonomyService(db).list_admin_sections()
    tags = await TaxonomyService(db).list_tags(PageParams(limit=100, cursor=None), None)
    return (
        [{"id": item.id, "label": _label(item, locale)} for item in sections if item.is_active],
        [{"id": item.id, "label": _tag_label(item, locale)} for item in tags.items],
    )


@router.get("/stories/new", response_class=HTMLResponse)
async def new_story(
    request: Request, staff: CurrentStaff, db: DbSession, locale: str | None = None
) -> HTMLResponse:
    if not staff.grants.has_anywhere(Perm.ARTICLE_CREATE):
        raise PermissionDenied("You cannot create stories")
    enabled = getattr(request.state, "enabled_locales", {"ar", "en"})
    chosen = locale if isinstance(locale, str) and locale in enabled else "ar"
    sections, tags = await _desk_choices(db, chosen)
    authors = await AuthorService(db).list_bylines()
    return templates.TemplateResponse(
        request,
        "admin/story_new.html",
        {
            "staff": staff,
            "sections": sections,
            "tags": tags,
            "authors": authors,
            "chosen_locale": chosen,
            "editor_dir": _direction(chosen),
            "article_types": list(ArticleType),
            "body_json": json.dumps(EMPTY_DOC),
            "error": None,
            "form": {},
        },
    )


@router.post("/stories/new", response_class=HTMLResponse)
async def create_story(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    section_id: Annotated[uuid.UUID, Form()],
    locale: Annotated[str, Form(max_length=10)],
    slug: Annotated[str, Form(max_length=200)],
    title: Annotated[str, Form(max_length=300)],
    body: Annotated[str, Form()],
    subtitle: Annotated[str, Form(max_length=500)] = "",
    excerpt: Annotated[str, Form(max_length=1000)] = "",
    article_type: Annotated[str, Form()] = ArticleType.NEWS.value,
    is_breaking: Annotated[str | None, Form()] = None,
    tag_ids: Annotated[list[str] | None, Form()] = None,
    author_ids: Annotated[list[str] | None, Form()] = None,
    lead_media_id: Annotated[str, Form()] = "",
    editor_dir: Annotated[str, Form()] = "",
) -> Response:
    form = {
        "section_id": str(section_id),
        "locale": locale,
        "slug": slug,
        "title": title,
        "subtitle": subtitle,
        "excerpt": excerpt,
        "article_type": article_type,
        "is_breaking": is_breaking == "1",
        "tag_ids": tag_ids or [],
        "author_ids": author_ids or [],
        "lead_media_id": lead_media_id.strip(),
    }
    try:
        chosen_authors = _ids(author_ids or [])
        if not chosen_authors:
            author = await UserService(db).ensure_author(staff.user)
            chosen_authors = [author.id]
        chosen_lead = uuid.UUID(form["lead_media_id"]) if form["lead_media_id"] else None
        created = await ArticleService(db).create(
            staff,
            ArticleCreate(
                section_id=section_id,
                article_type=ArticleType(article_type),
                author_ids=chosen_authors,
                tag_ids=_ids(tag_ids or []),
                is_breaking=is_breaking == "1",
                lead_media_id=chosen_lead,
                locale=locale,
                slug=slug,
                content=_content(title, subtitle, excerpt, body),
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        sections, tags = await _desk_choices(db, locale if locale in {"ar", "en"} else "ar")
        detail = exc.detail if isinstance(exc, AppError) else "Check the headline, slug, and body"
        status = exc.status_code if isinstance(exc, AppError) else 422
        return templates.TemplateResponse(
            request,
            "admin/story_new.html",
            {
                "staff": staff,
                "sections": sections,
                "tags": tags,
                "authors": await AuthorService(db).list_bylines(),
                "chosen_locale": locale,
                "editor_dir": editor_dir if editor_dir in {"rtl", "ltr"} else _direction(locale),
                "article_types": list(ArticleType),
                "body_json": body or json.dumps(EMPTY_DOC),
                "error": detail,
                "form": form,
            },
            status_code=status,
        )
    localization_id = created.localizations[0].id
    return RedirectResponse(f"/admin/stories/{localization_id}?notice=created", status_code=303)


@router.post("/stories/{localization_id}/lead")
async def set_lead(
    localization_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    media_id: Annotated[str, Form()] = "",
) -> RedirectResponse:
    story = await ArticleService(db).get_localization(staff, localization_id)
    chosen = uuid.UUID(media_id) if media_id else None
    try:
        await ArticleService(db).set_lead(staff, story.article_id, chosen)
    except (AppError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, AppError) else "Choose an uploaded image"
        return RedirectResponse(
            f"/admin/stories/{localization_id}?notice=error&detail={quote(detail or '')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/stories/{localization_id}?notice=saved", status_code=303)


@router.post("/stories/{localization_id}/legal-hold")
async def hold_story(
    localization_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    reason: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        await ArticleService(db).set_legal_hold(staff, localization_id, reason)
    except (AppError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, AppError) else "A reason is required"
        return RedirectResponse(
            f"/admin/stories/{localization_id}?notice=error&detail={quote(detail or '')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/stories/{localization_id}?notice=held", status_code=303)


@router.post("/stories/{localization_id}/legal-hold/clear")
async def clear_hold(
    localization_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    reason: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        await ArticleService(db).clear_legal_hold(staff, localization_id, reason)
    except (AppError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, AppError) else "A reason is required"
        return RedirectResponse(
            f"/admin/stories/{localization_id}?notice=error&detail={quote(detail or '')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/stories/{localization_id}?notice=cleared", status_code=303)


@router.post("/stories/{localization_id}/purge")
async def purge_story(
    localization_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    reason: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        await ArticleService(db).purge(staff, localization_id, reason)
    except (AppError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, AppError) else "A reason is required"
        return RedirectResponse(
            f"/admin/stories/{localization_id}?notice=error&detail={quote(detail or '')}",
            status_code=303,
        )
    return RedirectResponse("/admin/?notice=purged", status_code=303)


@router.post("/stories/{localization_id}/comments/{comment_id}/hide")
async def hide_story_comment(
    localization_id: uuid.UUID, comment_id: uuid.UUID, staff: CurrentStaff, db: DbSession
) -> RedirectResponse:
    await CommentService(db).hide_by_staff(staff, comment_id)
    return RedirectResponse(f"/admin/stories/{localization_id}?notice=saved", status_code=303)


@router.get("/stories/{localization_id}", response_class=HTMLResponse)
async def edit_story(
    request: Request,
    localization_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    notice: str | None = None,
    compare: uuid.UUID | None = None,
) -> HTMLResponse:
    page = await _edit_context(
        request, staff, db, localization_id, notice=notice, error=None, compare=compare
    )
    return templates.TemplateResponse(request, "admin/story.html", page)


@router.post("/stories/{localization_id}", response_class=HTMLResponse)
async def save_story(
    request: Request,
    localization_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    title: Annotated[str, Form(max_length=300)],
    body: Annotated[str, Form()],
    base_revision_id: Annotated[uuid.UUID, Form()],
    subtitle: Annotated[str, Form(max_length=500)] = "",
    excerpt: Annotated[str, Form(max_length=1000)] = "",
) -> Response:
    try:
        await ArticleService(db).save_revision(
            staff,
            localization_id,
            RevisionCreate(
                base_revision_id=base_revision_id,
                content=_content(title, subtitle, excerpt, body),
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, AppError) else "Check the headline and body"
        status = exc.status_code if isinstance(exc, AppError) else 422
        page = await _edit_context(
            request, staff, db, localization_id, notice=None, error=detail, compare=None
        )
        return templates.TemplateResponse(request, "admin/story.html", page, status_code=status)
    return RedirectResponse(f"/admin/stories/{localization_id}?notice=saved", status_code=303)


@router.post("/stories/{localization_id}/slug")
async def change_story_slug(
    localization_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    slug: Annotated[str, Form(max_length=200)],
) -> RedirectResponse:
    try:
        await ArticleService(db).change_slug(staff, localization_id, SlugChange(slug=slug.strip()))
    except (AppError, ValidationError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, AppError) else "That slug could not be used"
        return RedirectResponse(
            f"/admin/stories/{localization_id}?notice=error&detail={quote(detail or '')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/stories/{localization_id}?notice=slug", status_code=303)


@router.post("/stories/{localization_id}/corrections")
async def add_story_correction(
    localization_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    kind: Annotated[str, Form()],
    text: Annotated[str, Form(max_length=2000)],
) -> RedirectResponse:
    try:
        await ArticleService(db).add_correction(
            staff,
            localization_id,
            CorrectionCreate(kind=CorrectionKind(kind), text=text.strip()),
        )
    except (AppError, ValidationError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, AppError) else "That note could not be added"
        return RedirectResponse(
            f"/admin/stories/{localization_id}?notice=error&detail={quote(detail or '')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/stories/{localization_id}?notice=corrected", status_code=303)


@router.post("/stories/{localization_id}/transition")
async def move_story(
    localization_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    action: Annotated[str, Form()],
    lock_version: Annotated[int, Form()],
    reason: Annotated[str, Form(max_length=2000)] = "",
    publish_at: Annotated[str, Form()] = "",
    unpublish_at: Annotated[str, Form()] = "",
    takedown_reason: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        chosen = ArticleAction(action)
        await ArticleService(db).transition(
            staff,
            localization_id,
            TransitionRequest(
                action=chosen,
                lock_version=lock_version,
                reason=reason.strip() or None,
                publish_at=_when(publish_at),
                unpublish_at=_when(unpublish_at),
                takedown_reason=TakedownReason(takedown_reason) if takedown_reason else None,
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, AppError) else "That action could not be applied"
        return RedirectResponse(
            f"/admin/stories/{localization_id}?notice=error&detail={quote(detail or '')}",
            status_code=303,
        )
    if chosen is ArticleAction.DELETE:
        return RedirectResponse("/admin/", status_code=303)
    return RedirectResponse(f"/admin/stories/{localization_id}?notice=moved", status_code=303)


@router.post("/stories/{article_id}/localizations")
async def add_translation(
    article_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    locale: Annotated[str, Form(max_length=10)],
    slug: Annotated[str, Form(max_length=200)],
    title: Annotated[str, Form(max_length=300)],
    body: Annotated[str, Form()],
    subtitle: Annotated[str, Form(max_length=500)] = "",
    excerpt: Annotated[str, Form(max_length=1000)] = "",
) -> RedirectResponse:
    try:
        created = await ArticleService(db).add_localization(
            staff,
            article_id,
            LocalizationCreate(
                locale=locale,
                slug=slug,
                content=_content(title, subtitle, excerpt, body),
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, AppError) else "Translation could not be added"
        quoted = quote(detail or "")
        return RedirectResponse(f"/admin/?notice=error&detail={quoted}", status_code=303)
    return RedirectResponse(f"/admin/stories/{created.id}?notice=created", status_code=303)


@router.post("/stories/{localization_id}/revisions/{revision_id}/restore")
async def restore_on_desk(
    localization_id: uuid.UUID,
    revision_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    base_revision_id: Annotated[uuid.UUID, Form()],
    change_note: Annotated[str, Form(max_length=500)] = "",
) -> RedirectResponse:
    try:
        await ArticleService(db).restore_revision(
            staff,
            localization_id,
            revision_id,
            RestoreRequest(
                base_revision_id=base_revision_id, change_note=change_note.strip() or None
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, AppError) else "That revision could not be restored"
        return RedirectResponse(
            f"/admin/stories/{localization_id}?notice=error&detail={quote(detail or '')}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/stories/{localization_id}?notice=restored", status_code=303)


async def _edit_context(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    localization_id: uuid.UUID,
    *,
    notice: str | None,
    error: str | None,
    compare: uuid.UUID | None,
) -> dict:
    articles = ArticleService(db)
    story = await articles.get_localization(staff, localization_id)
    article = await articles.get_admin(staff, story.article_id)
    revisions = await articles.list_revisions(
        staff, localization_id, PageParams(limit=50, cursor=None)
    )
    diff = None
    if compare is not None:
        diff = await articles.diff_revisions(
            staff, localization_id, compare, story.current_revision.id
        )
    content = story.current_revision.content
    missing = [
        code for code in ("ar", "en") if code not in {item.locale for item in article.localizations}
    ]
    detail = request.query_params.get("detail")
    visible = _visible_actions(
        staff, article.section_id, article.created_by, story.available_actions
    )
    return {
        "staff": staff,
        "story": story,
        "article": article,
        "editor_dir": _direction(story.locale),
        "body_json": json.dumps(content.body),
        "action_groups": _group_actions(visible),
        "can_unpublish": ArticleAction.UNPUBLISH in visible,
        "takedown_reasons": list(TakedownReason),
        "missing_locales": missing,
        "translation_dir": _direction(missing[0]) if missing else "rtl",
        "empty_body": json.dumps(EMPTY_DOC),
        "notice": notice,
        "error": error or detail,
        "revisions": revisions.items,
        "diff": diff,
        "timeline": await articles.history(staff, localization_id),
        "can_hold": staff.grants.has(Perm.ARTICLE_REVIEW, section_id=article.section_id)
        and not story.legal_hold
        and story.status is not ArticleStatus.ARCHIVED,
        "can_clear_hold": story.legal_hold
        and staff.grants.has(Perm.ARTICLE_CLEAR_LEGAL, section_id=article.section_id),
        "can_purge": staff.grants.has_anywhere(Perm.ARTICLE_PURGE),
        "can_restore": staff.grants.has(
            Perm.ARTICLE_RESTORE_REVISION, section_id=article.section_id
        ),
        "can_change_slug": _can_change_slug(staff, article, story),
        "can_correct": story.published_at is not None
        and story.status is not ArticleStatus.ARCHIVED
        and staff.grants.has(Perm.ARTICLE_CORRECT, section_id=article.section_id),
        "correction_kinds": list(CorrectionKind),
        "comments": await CommentService(db).list_public(localization_id, None),
        "can_hide_comments": staff.grants.has(Perm.ARTICLE_EDIT, section_id=article.section_id),
    }


def _optional_uuid(value: str) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _optional_status(value: str) -> ArticleStatus | None:
    if not value:
        return None
    try:
        return ArticleStatus(value)
    except ValueError:
        return None


def _optional_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@router.get("/stories", response_class=HTMLResponse)
async def stories_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    status: Annotated[str, Query(max_length=32)] = "",
    locale: Annotated[str, Query(max_length=10)] = "",
    section_id: Annotated[str, Query(max_length=36)] = "",
    tag_id: Annotated[str, Query(max_length=36)] = "",
    author_id: Annotated[str, Query(max_length=36)] = "",
    reviewed_by: Annotated[str, Query(max_length=36)] = "",
    updated_from: Annotated[str, Query(max_length=10)] = "",
    updated_to: Annotated[str, Query(max_length=10)] = "",
    q: Annotated[str, Query(max_length=200)] = "",
    page: PageQuery = 1,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> HTMLResponse:
    fragment = is_fragment(request, cursor)
    bounds = listing_params(_STORY_PAGE, page, fragment, cursor)
    ui = _request_locale(request)
    sections = await TaxonomyService(db).list_admin_sections()
    tags = (await TaxonomyService(db).list_tags(PageParams(limit=100, cursor=None), None)).items
    authors = await AuthorService(db).list_bylines()
    staff_rows = (
        await db.scalars(select(User).where(User.kind == UserKind.STAFF).order_by(User.email))
    ).all()
    stories, next_cursor = await story_rows(
        staff,
        db,
        cursor=bounds.cursor,
        limit=bounds.limit,
        status=_optional_status(status),
        locale=locale.strip() or None,
        section_id=_optional_uuid(section_id),
        tag_id=_optional_uuid(tag_id),
        author_id=_optional_uuid(author_id),
        reviewed_by=_optional_uuid(reviewed_by),
        updated_from=_optional_date(updated_from),
        updated_to=_optional_date(updated_to),
        q=q.strip() or None,
        section_names={item.id: _label(item, ui) for item in sections},
        author_names={item.id: item.display_name for item in authors},
        editor_names={item.id: item.display_name or item.email for item in staff_rows},
    )
    filters = {
        "status": status,
        "locale": locale,
        "section_id": section_id,
        "tag_id": tag_id,
        "author_id": author_id,
        "reviewed_by": reviewed_by,
        "updated_from": updated_from,
        "updated_to": updated_to,
        "q": q,
    }
    return templates.TemplateResponse(
        request,
        "admin/fragments/stories.html" if fragment else "admin/stories.html",
        {
            "staff": staff,
            "stories": stories,
            "statuses": list(ArticleStatus),
            "sections": [(item.id, _label(item, ui)) for item in sections],
            "tags": [(item.id, _tag_label(item, ui)) for item in tags],
            "authors": authors,
            "editors": [(item.id, item.display_name or item.email) for item in staff_rows],
            "filters": filters,
            **pager_context(
                path="/admin/stories",
                page=page,
                extra=filters,
                next_cursor=next_cursor,
                fragment=fragment,
                prev_key="manage.previous",
                more_key="manage.more",
            ),
        },
    )


async def story_rows(
    staff: CurrentStaff,
    db: DbSession,
    *,
    cursor: str | None,
    limit: int,
    status: ArticleStatus | None,
    locale: str | None,
    section_id: uuid.UUID | None,
    tag_id: uuid.UUID | None,
    author_id: uuid.UUID | None,
    reviewed_by: uuid.UUID | None,
    updated_from: date | None,
    updated_to: date | None,
    q: str | None,
    section_names: dict[uuid.UUID, str],
    author_names: dict[uuid.UUID, str],
    editor_names: dict[uuid.UUID, str],
) -> tuple[list[StoryRow], str | None]:
    opened, closed = edition_window(updated_from, updated_to)
    page = await ArticleService(db).list_admin(
        staff,
        PageParams(limit=limit, cursor=cursor),
        status=status,
        locale=locale,
        section_id=section_id,
        author_id=author_id,
        tag_id=tag_id,
        reviewed_by=reviewed_by,
        updated_from=opened,
        updated_to=closed,
        q=q,
    )
    rows: list[StoryRow] = []
    for article in page.items:
        bylines = tuple(author_names[item] for item in article.author_ids if item in author_names)
        rows.extend(
            StoryRow(
                localization_id=item.id,
                title=item.title or item.slug,
                locale=item.locale,
                slug=item.slug,
                status=item.status.value,
                section=section_names.get(article.section_id, ""),
                bylines=bylines,
                editor=editor_names.get(item.reviewed_by) if item.reviewed_by else None,
                updated_at=item.updated_at,
                legal_hold=item.legal_hold,
            )
            for item in article.localizations
        )
    return rows, page.next_cursor
