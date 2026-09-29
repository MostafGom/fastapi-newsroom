from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.audit.models import AuditEvent
from newsroom.auth.models import AuthSession, SessionKind
from newsroom.auth.service import utcnow
from newsroom.core.errors import NotFound
from newsroom.core.security import hash_token
from newsroom.users.models import User, UserKind
from newsroom.users.service import EmailTaken, UserService
from newsroom.worker.jobs import SESSION_RETENTION, prune_sessions


async def test_create_staff_normalizes_email_and_audits(db: AsyncSession) -> None:
    user = await UserService(db).create_staff(
        email="  Chief@Example.COM ",
        display_name="Chief",
        password="long-enough-password",
        role_key="super_admin",
    )
    assert user.email == "chief@example.com"
    assert user.kind is UserKind.STAFF
    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "user.created", AuditEvent.entity_id == str(user.id)
        )
    )
    assert event is not None
    assert event.after == {
        "email": "chief@example.com",
        "kind": "staff",
        "role": "super_admin",
        "section_id": None,
    }


async def test_duplicate_email_is_rejected(db: AsyncSession) -> None:
    service = UserService(db)
    await service.create_staff(email="dup@example.com", display_name="A", password="x" * 12)
    with pytest.raises(EmailTaken):
        await service.create_staff(email="DUP@example.com", display_name="B", password="x" * 12)


async def test_unknown_role_is_rejected(db: AsyncSession) -> None:
    with pytest.raises(NotFound):
        await UserService(db).create_staff(
            email="r@example.com", display_name="R", password="x" * 12, role_key="nope"
        )


async def test_database_enforces_lowercase_email(db: AsyncSession) -> None:
    db.add(User(email="Mixed@Example.com", kind=UserKind.READER))
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_prune_sessions_keeps_recent_ones(db: AsyncSession) -> None:
    user = await UserService(db).create_staff(
        email="p@example.com", display_name="P", password="x" * 12
    )
    now = utcnow()
    old = now - SESSION_RETENTION - timedelta(days=1)
    db.add_all(
        [
            AuthSession(
                user_id=user.id,
                token_hash=hash_token("old"),
                kind=SessionKind.STAFF_WEB,
                expires_at=old,
            ),
            AuthSession(
                user_id=user.id,
                token_hash=hash_token("live"),
                kind=SessionKind.STAFF_WEB,
                expires_at=now + timedelta(hours=1),
            ),
        ]
    )
    await db.commit()
    assert await prune_sessions(db) == 1
    remaining = (
        await db.scalars(select(AuthSession.token_hash).where(AuthSession.user_id == user.id))
    ).all()
    assert remaining == [hash_token("live")]
