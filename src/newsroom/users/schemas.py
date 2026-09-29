import uuid

from pydantic import EmailStr, Field

from newsroom.core.schemas import Schema, UtcDatetime
from newsroom.users.models import UserKind, UserStatus


class UserOut(Schema):
    id: uuid.UUID
    email: EmailStr
    kind: UserKind
    status: UserStatus
    display_name: str | None
    email_verified_at: UtcDatetime | None
    last_login_at: UtcDatetime | None
    created_at: UtcDatetime


class StaffCreate(Schema):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    job_title: str | None = Field(default=None, max_length=120)
    password: str = Field(min_length=12, max_length=1024)


class UserUpdate(Schema):
    status: UserStatus | None = None
    display_name: str | None = Field(default=None, max_length=120)
    job_title: str | None = Field(default=None, max_length=120)


class RoleGrantCreate(Schema):
    role_key: str = Field(max_length=64)
    section_id: uuid.UUID | None = None


class UserRoleOut(Schema):
    id: uuid.UUID
    role_key: str
    section_id: uuid.UUID | None
    granted_by: uuid.UUID | None
    created_at: UtcDatetime


class ReaderProfileUpdate(Schema):
    display_name: str | None = Field(default=None, max_length=120)
    preferred_locale: str | None = Field(default=None, max_length=10)
    newsletter_opt_in: bool | None = None


class ReaderProfileOut(Schema):
    email: EmailStr
    display_name: str | None
    preferred_locale: str | None
    newsletter_opt_in: bool


class RoleOut(Schema):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    rank: int
    is_system: bool
    permissions: list[str]
