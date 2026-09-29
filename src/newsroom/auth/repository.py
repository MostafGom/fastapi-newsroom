import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.auth.models import AuthSession


class SessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_token_hash(self, token_hash: bytes) -> AuthSession | None:
        result = await self.db.execute(
            select(AuthSession).where(AuthSession.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    def add(self, session: AuthSession) -> None:
        self.db.add(session)

    async def revoke_all_for_user(self, user_id: uuid.UUID, now: datetime) -> None:
        await self.db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
