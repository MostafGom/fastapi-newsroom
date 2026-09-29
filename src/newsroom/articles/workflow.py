"""Article localization state machine.

Mirrors docs/04-workflow.md and docs/06-editorial-scenarios.md.
"""

from dataclasses import dataclass
from enum import StrEnum

from newsroom.authz.permissions import Perm
from newsroom.core.errors import Conflict


class ArticleStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    COPY_EDITING = "copy_editing"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    KILLED = "killed"
    ARCHIVED = "archived"


class ArticleAction(StrEnum):
    SUBMIT = "submit"
    WITHDRAW = "withdraw"
    REQUEST_CHANGES = "request_changes"
    SEND_TO_COPY = "send_to_copy"
    RETURN_TO_WRITER = "return_to_writer"
    FINISH_COPY = "finish_copy"
    APPROVE = "approve"
    SCHEDULE = "schedule"
    CANCEL_SCHEDULE = "cancel_schedule"
    PUBLISH = "publish"
    PUBLISH_UPDATE = "publish_update"
    UNPUBLISH = "unpublish"
    REPUBLISH = "republish"
    KILL = "kill"
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    DELETE = "delete"


class TakedownReason(StrEnum):
    """Why a live story was taken down. Stored on the audit event, shown internally."""

    LEGAL = "legal"
    MAJOR_ERROR = "major_error"
    DUPLICATE = "duplicate"
    SAFETY = "safety"
    OTHER = "other"


class CorrectionKind(StrEnum):
    """Public note attached to a live story. Readers see the kind as a label."""

    CORRECTION = "correction"
    CLARIFICATION = "clarification"
    UPDATE = "update"


@dataclass(frozen=True, slots=True)
class Transition:
    action: ArticleAction
    sources: frozenset[ArticleStatus]
    target: ArticleStatus | None
    permission: Perm
    requires_reason: bool = False
    owner_may_act: bool = False


S = ArticleStatus
A = ArticleAction

TRANSITIONS: dict[ArticleAction, Transition] = {
    t.action: t
    for t in (
        Transition(
            A.SUBMIT,
            frozenset({S.DRAFT, S.CHANGES_REQUESTED}),
            S.IN_REVIEW,
            Perm.ARTICLE_SUBMIT,
            owner_may_act=True,
        ),
        Transition(
            A.WITHDRAW,
            frozenset({S.IN_REVIEW}),
            S.DRAFT,
            Perm.ARTICLE_SUBMIT,
            owner_may_act=True,
        ),
        Transition(
            A.REQUEST_CHANGES,
            frozenset({S.IN_REVIEW, S.COPY_EDITING, S.APPROVED}),
            S.CHANGES_REQUESTED,
            Perm.ARTICLE_REVIEW,
            requires_reason=True,
        ),
        Transition(A.SEND_TO_COPY, frozenset({S.IN_REVIEW}), S.COPY_EDITING, Perm.ARTICLE_REVIEW),
        Transition(
            A.RETURN_TO_WRITER,
            frozenset({S.COPY_EDITING}),
            S.CHANGES_REQUESTED,
            Perm.ARTICLE_COPY,
            requires_reason=True,
        ),
        Transition(A.FINISH_COPY, frozenset({S.COPY_EDITING}), S.APPROVED, Perm.ARTICLE_COPY),
        Transition(
            A.APPROVE,
            frozenset({S.IN_REVIEW}),
            S.APPROVED,
            Perm.ARTICLE_REVIEW,
            requires_reason=True,
        ),
        Transition(A.SCHEDULE, frozenset({S.APPROVED}), S.SCHEDULED, Perm.ARTICLE_PUBLISH),
        Transition(A.CANCEL_SCHEDULE, frozenset({S.SCHEDULED}), S.APPROVED, Perm.ARTICLE_PUBLISH),
        Transition(
            A.PUBLISH, frozenset({S.APPROVED, S.SCHEDULED}), S.PUBLISHED, Perm.ARTICLE_PUBLISH
        ),
        Transition(A.PUBLISH_UPDATE, frozenset({S.PUBLISHED}), S.PUBLISHED, Perm.ARTICLE_PUBLISH),
        Transition(
            A.UNPUBLISH,
            frozenset({S.PUBLISHED}),
            S.UNPUBLISHED,
            Perm.ARTICLE_UNPUBLISH,
            requires_reason=True,
        ),
        Transition(A.REPUBLISH, frozenset({S.UNPUBLISHED}), S.PUBLISHED, Perm.ARTICLE_PUBLISH),
        Transition(
            A.KILL,
            frozenset(
                {S.DRAFT, S.IN_REVIEW, S.COPY_EDITING, S.CHANGES_REQUESTED, S.APPROVED, S.SCHEDULED}
            ),
            S.KILLED,
            Perm.ARTICLE_REVIEW,
            requires_reason=True,
        ),
        Transition(
            A.ARCHIVE,
            frozenset({S.PUBLISHED, S.UNPUBLISHED, S.KILLED}),
            S.ARCHIVED,
            Perm.ARTICLE_ARCHIVE,
        ),
        Transition(A.UNARCHIVE, frozenset({S.ARCHIVED}), S.UNPUBLISHED, Perm.ARTICLE_ARCHIVE),
        Transition(
            A.DELETE,
            frozenset({S.DRAFT, S.CHANGES_REQUESTED}),
            None,
            Perm.ARTICLE_DELETE_DRAFT,
            owner_may_act=True,
        ),
    )
}

PUBLIC_STATUSES = frozenset({S.PUBLISHED})
# A writer may change their own text only here. In review and on the copy desk, the desk owns it.
# On a live story they may save a proposal; it does not replace the published revision.
EDITABLE_BY_OWNER = frozenset({S.DRAFT, S.CHANGES_REQUESTED, S.PUBLISHED})
PRE_PUBLISH = frozenset(
    {S.DRAFT, S.IN_REVIEW, S.COPY_EDITING, S.CHANGES_REQUESTED, S.APPROVED, S.SCHEDULED}
)


class IllegalTransition(Conflict):
    code = "illegal_transition"


class ReasonRequired(Conflict):
    status_code = 422
    code = "reason_required"


def resolve_transition(
    current: ArticleStatus,
    action: ArticleAction,
    *,
    reason: str | None = None,
    ever_published: bool = False,
) -> Transition:
    """Validate a requested action against the state machine. Does not check permissions."""
    transition = TRANSITIONS[action]
    if current not in transition.sources:
        raise IllegalTransition(f"Cannot {action.value} an article that is {current.value}")
    if action in {A.DELETE, A.KILL} and ever_published:
        raise IllegalTransition("A story that has been published cannot be deleted or killed")
    if transition.requires_reason and not (reason and reason.strip()):
        raise ReasonRequired(f"A reason is required to {action.value}")
    return transition


def available_actions(current: ArticleStatus, *, ever_published: bool) -> list[ArticleAction]:
    return [
        t.action
        for t in TRANSITIONS.values()
        if current in t.sources and not (t.action in {A.DELETE, A.KILL} and ever_published)
    ]
