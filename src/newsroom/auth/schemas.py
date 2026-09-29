import uuid
from enum import StrEnum

from pydantic import EmailStr, Field

from newsroom.core.schemas import Schema, UtcDatetime
from newsroom.users.models import UserKind


class Audience(StrEnum):
    READER = "reader"
    STAFF = "staff"


class LoginRequest(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    audience: Audience = Audience.READER


class RegisterRequest(Schema):
    email: EmailStr
    password: str = Field(min_length=10, max_length=1024)
    display_name: str | None = Field(default=None, max_length=120)
    preferred_locale: str | None = Field(default=None, max_length=10)


class SessionOut(Schema):
    expires_at: UtcDatetime
    csrf_token: str


class GrantOut(Schema):
    role: str
    section_id: uuid.UUID | None


class MeOut(Schema):
    id: uuid.UUID
    email: EmailStr
    kind: UserKind
    display_name: str | None
    roles: list[GrantOut] = []
    permissions: list[str] = []
