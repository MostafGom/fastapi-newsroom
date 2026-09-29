import pytest

from newsroom.articles.workflow import (
    TRANSITIONS,
    ArticleAction,
    ArticleStatus,
    IllegalTransition,
    ReasonRequired,
    available_actions,
    resolve_transition,
)
from newsroom.authz.permissions import Perm

S = ArticleStatus
A = ArticleAction

EXPECTED_EDGES = {
    (A.SUBMIT, S.DRAFT): S.IN_REVIEW,
    (A.SUBMIT, S.CHANGES_REQUESTED): S.IN_REVIEW,
    (A.WITHDRAW, S.IN_REVIEW): S.DRAFT,
    (A.REQUEST_CHANGES, S.IN_REVIEW): S.CHANGES_REQUESTED,
    (A.REQUEST_CHANGES, S.COPY_EDITING): S.CHANGES_REQUESTED,
    (A.REQUEST_CHANGES, S.APPROVED): S.CHANGES_REQUESTED,
    (A.SEND_TO_COPY, S.IN_REVIEW): S.COPY_EDITING,
    (A.RETURN_TO_WRITER, S.COPY_EDITING): S.CHANGES_REQUESTED,
    (A.FINISH_COPY, S.COPY_EDITING): S.APPROVED,
    (A.APPROVE, S.IN_REVIEW): S.APPROVED,
    (A.SCHEDULE, S.APPROVED): S.SCHEDULED,
    (A.CANCEL_SCHEDULE, S.SCHEDULED): S.APPROVED,
    (A.PUBLISH, S.APPROVED): S.PUBLISHED,
    (A.PUBLISH, S.SCHEDULED): S.PUBLISHED,
    (A.PUBLISH_UPDATE, S.PUBLISHED): S.PUBLISHED,
    (A.UNPUBLISH, S.PUBLISHED): S.UNPUBLISHED,
    (A.REPUBLISH, S.UNPUBLISHED): S.PUBLISHED,
    (A.KILL, S.DRAFT): S.KILLED,
    (A.KILL, S.IN_REVIEW): S.KILLED,
    (A.KILL, S.COPY_EDITING): S.KILLED,
    (A.KILL, S.CHANGES_REQUESTED): S.KILLED,
    (A.KILL, S.APPROVED): S.KILLED,
    (A.KILL, S.SCHEDULED): S.KILLED,
    (A.ARCHIVE, S.PUBLISHED): S.ARCHIVED,
    (A.ARCHIVE, S.UNPUBLISHED): S.ARCHIVED,
    (A.ARCHIVE, S.KILLED): S.ARCHIVED,
    (A.UNARCHIVE, S.ARCHIVED): S.UNPUBLISHED,
    (A.DELETE, S.DRAFT): None,
    (A.DELETE, S.CHANGES_REQUESTED): None,
}


def test_every_action_has_a_transition() -> None:
    assert set(TRANSITIONS) == set(ArticleAction)


def test_transition_table_matches_the_documented_edges() -> None:
    actual = {(t.action, source): t.target for t in TRANSITIONS.values() for source in t.sources}
    assert actual == EXPECTED_EDGES


@pytest.mark.parametrize(("edge", "target"), EXPECTED_EDGES.items())
def test_documented_edges_resolve(
    edge: tuple[ArticleAction, ArticleStatus], target: object
) -> None:
    action, source = edge
    transition = resolve_transition(source, action, reason="because")
    assert transition.target == target


@pytest.mark.parametrize("status", list(ArticleStatus))
@pytest.mark.parametrize("action", list(ArticleAction))
def test_undocumented_edges_are_rejected(status: ArticleStatus, action: ArticleAction) -> None:
    if (action, status) in EXPECTED_EDGES:
        return
    with pytest.raises(IllegalTransition):
        resolve_transition(status, action, reason="because")


@pytest.mark.parametrize(
    "action", [A.UNPUBLISH, A.REQUEST_CHANGES, A.APPROVE, A.RETURN_TO_WRITER, A.KILL]
)
def test_reason_is_mandatory(action: ArticleAction) -> None:
    source = next(iter(TRANSITIONS[action].sources))
    with pytest.raises(ReasonRequired):
        resolve_transition(source, action, reason="   ")


def test_published_content_can_never_be_deleted_or_killed() -> None:
    for action in (A.DELETE, A.KILL):
        with pytest.raises(IllegalTransition):
            resolve_transition(S.DRAFT, action, ever_published=True, reason="too late")
        assert action not in available_actions(S.DRAFT, ever_published=True)
    assert A.DELETE in available_actions(S.DRAFT, ever_published=False)
    assert A.KILL in available_actions(S.DRAFT, ever_published=False)


def test_skipping_copy_is_the_only_approve_and_it_needs_a_reason() -> None:
    assert TRANSITIONS[A.APPROVE].sources == frozenset({S.IN_REVIEW})
    assert TRANSITIONS[A.FINISH_COPY].permission is Perm.ARTICLE_COPY
    resolve_transition(S.COPY_EDITING, A.FINISH_COPY)


def test_no_writer_permission_reaches_publication() -> None:
    publishing = {A.PUBLISH, A.PUBLISH_UPDATE, A.REPUBLISH, A.SCHEDULE, A.UNPUBLISH}
    for action in publishing:
        assert TRANSITIONS[action].permission in {Perm.ARTICLE_PUBLISH, Perm.ARTICLE_UNPUBLISH}
        assert not TRANSITIONS[action].owner_may_act
