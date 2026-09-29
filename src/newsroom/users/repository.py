import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.users.models import User, UserKind


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == normalize_email(email)))
        return result.scalar_one_or_none()

    async def count_by_kind(self, kind: UserKind) -> int:
        result = await self.db.execute(select(func.count()).where(User.kind == kind))
        return result.scalar_one()

    def add(self, user: User) -> None:
        self.db.add(user)
