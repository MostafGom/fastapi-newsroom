import uuid

import pytest

from newsroom.authz.authorizer import Grant, Grants
from newsroom.authz.permissions import SYSTEM_ROLES, Perm
from newsroom.authz.policies import ensure_can_grant_role, ensure_outranks
from newsroom.core.errors import PermissionDenied

ROLES = {r.key: r for r in SYSTEM_ROLES}
POLITICS = uuid.uuid7()
SPORTS = uuid.uuid7()


def grant(role_key: str, section_id: uuid.UUID | None = None) -> Grant:
    role = ROLES[role_key]
    return Grant(role.key, role.rank, section_id, frozenset(p.value for p in role.permissions))


def test_section_scoped_editor_only_publishes_in_their_section() -> None:
    grants = Grants([grant("writer"), grant("editor", POLITICS)])
    assert grants.has(Perm.ARTICLE_PUBLISH, section_id=POLITICS)
    assert not grants.has(Perm.ARTICLE_PUBLISH, section_id=SPORTS)
    assert not grants.has(Perm.ARTICLE_PUBLISH)
    assert grants.has_anywhere(Perm.ARTICLE_PUBLISH)
    assert grants.sections_with(Perm.ARTICLE_PUBLISH) == {POLITICS}


def test_global_grant_covers_every_section() -> None:
    grants = Grants([grant("editor")])
    assert grants.has(Perm.ARTICLE_PUBLISH, section_id=SPORTS)
    assert grants.sections_with(Perm.ARTICLE_PUBLISH) is None


def test_writer_cannot_review_or_publish() -> None:
    grants = Grants([grant("writer")])
    for perm in (Perm.ARTICLE_REVIEW, Perm.ARTICLE_PUBLISH, Perm.ARTICLE_UNPUBLISH):
        assert not grants.has_anywhere(perm)


def test_only_super_admin_can_purge_or_manage_roles() -> None:
    for key, role in ROLES.items():
        expected = key == "super_admin"
        assert (Perm.ARTICLE_PURGE in role.permissions) is expected
        assert (Perm.ROLE_MANAGE in role.permissions) is expected


def test_desk_roles_stack_without_giving_copy_editors_the_publish_button() -> None:
    writer, copy_editor, editor, admin, super_admin = sorted(SYSTEM_ROLES, key=lambda r: r.rank)
    assert writer.permissions <= editor.permissions
    assert copy_editor.permissions <= editor.permissions
    assert editor.permissions <= admin.permissions
    assert admin.permissions <= super_admin.permissions
    assert Perm.ARTICLE_PUBLISH not in copy_editor.permissions
    assert Perm.ARTICLE_COPY not in writer.permissions
    assert not writer.permissions <= copy_editor.permissions


def test_rank_rules() -> None:
    admin = Grants([grant("admin")])
    ensure_outranks(admin, Grants([grant("editor")]))
    with pytest.raises(PermissionDenied):
        ensure_outranks(admin, Grants([grant("admin")]))
    with pytest.raises(PermissionDenied):
        ensure_can_grant_role(admin, ROLES["admin"].rank)
    ensure_can_grant_role(Grants([grant("super_admin")]), ROLES["admin"].rank)
