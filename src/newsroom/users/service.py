import uuid
from datetime import UTC, datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from newsroom.articles.models import Author, AuthorKind, AuthorTranslation
from newsroom.audit.service import record_event
from newsroom.auth.principal import Principal
from newsroom.authz.authorizer import DbAuthorizer
from newsroom.authz.models import Permission, Role, UserRole
from newsroom.authz.permissions import SUPER_ADMIN_ROLE, Perm
from newsroom.authz.policies import ensure_can_grant_role, ensure_outranks
from newsroom.core.errors import Conflict, NotFound, PermissionDenied
from newsroom.core.schemas import Page, PageParams, decode_cursor, encode_cursor
from newsroom.core.security import hash_password
from newsroom.users.models import ReaderProfile, StaffProfile, User, UserKind, UserStatus
from newsroom.users.repository import UserRepository, normalize_email
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


class EmailTaken(Conflict):
    code = "email_taken"


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.users = UserRepository(db)

    async def create_staff(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        role_key: str | None = None,
        section_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        job_title: str | None = None,
    ) -> User:
        """Create a staff user, optionally with an initial role, in one audited transaction.

        Rank checks against ``actor_id`` belong to the staff-users slice; the CLI calls this
        as the system actor.
        """
        email = normalize_email(email)
        if await self.users.get_by_email(email) is not None:
            raise EmailTaken(f"{email} is already registered")

        user = User(
            email=email,
            password_hash=hash_password(password),
            kind=UserKind.STAFF,
            status=UserStatus.ACTIVE,
            staff_profile=StaffProfile(display_name=display_name, job_title=job_title),
        )
        self.users.add(user)
        await self.db.flush()

        granted: str | None = None
        if role_key is not None:
            role = await self.db.scalar(select(Role).where(Role.key == role_key))
            if role is None:
                raise NotFound(f"Unknown role '{role_key}'. Run `newsroom seed` first.")
            self.db.add(
                UserRole(
                    user_id=user.id, role_id=role.id, section_id=section_id, granted_by=actor_id
                )
            )
            granted = role.key

        record_event(
            self.db,
            actor_id=actor_id,
            action="user.created",
            entity_type="user",
            entity_id=user.id,
            after={
                "email": email,
                "kind": UserKind.STAFF.value,
                "role": granted,
                "section_id": str(section_id) if section_id else None,
            },
        )
        self._attach_author(user)
        await self.db.commit()
        return user

    async def ensure_author(self, user: User) -> Author:
        """Staff created before bylines existed still need an author row to file a story."""
        found = await self.db.scalar(select(Author).where(Author.user_id == user.id))
        if found is not None:
            return found
        self._attach_author(user)
        await self.db.commit()
        found = await self.db.scalar(select(Author).where(Author.user_id == user.id))
        if found is None:
            raise NotFound("Author profile was not created")
        return found

    def _attach_author(self, user: User) -> None:
        slug = user.email.replace("@", "-").replace(".", "-")
        name = user.display_name or slug
        author = Author(user_id=user.id, kind=AuthorKind.STAFF, key=slug)
        author.translations = [
            AuthorTranslation(locale=code, display_name=name, slug=slug) for code in ("ar", "en")
        ]
        self.db.add(author)

    def to_out(self, user: User) -> UserOut:
        return UserOut.model_validate(user)

    async def list_users(
        self, paging: PageParams, *, kind: UserKind | None, status: UserStatus | None, q: str | None
    ) -> Page[UserOut]:
        stmt = select(User).order_by(User.created_at.desc(), User.id.desc())
        if kind is not None:
            stmt = stmt.where(User.kind == kind)
        if status is not None:
            stmt = stmt.where(User.status == status)
        if q:
            stmt = stmt.where(User.email.contains(q.strip().lower()))
        if paging.cursor:
            raw = decode_cursor(paging.cursor)
            stmt = stmt.where(
                tuple_(User.created_at, User.id)
                < tuple_(datetime.fromisoformat(raw["created_at"]), uuid.UUID(raw["id"]))
            )
        rows = list((await self.db.scalars(stmt.limit(paging.limit + 1))).all())
        next_cursor = None
        if len(rows) > paging.limit:
            rows = rows[: paging.limit]
            last = rows[-1]
            next_cursor = encode_cursor(
                {"created_at": last.created_at.isoformat(), "id": str(last.id)}
            )
        return Page(items=[self.to_out(user) for user in rows], next_cursor=next_cursor)

    async def get_user(self, user_id: uuid.UUID) -> UserOut:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFound("User not found")
        return self.to_out(user)

    async def list_role_grants(self, user_id: uuid.UUID) -> list[UserRoleOut]:
        rows = (
            await self.db.scalars(
                select(UserRole).where(UserRole.user_id == user_id).order_by(UserRole.created_at)
            )
        ).all()
        return [
            UserRoleOut(
                id=grant.id,
                role_key=grant.role.key,
                section_id=grant.section_id,
                granted_by=grant.granted_by,
                created_at=grant.created_at,
            )
            for grant in rows
        ]

    async def create_staff_account(self, actor: Principal, payload: StaffCreate) -> UserOut:
        await self._require_manage(actor, target=None, role_key=None)
        user = await self.create_staff(
            email=payload.email,
            display_name=payload.display_name,
            password=payload.password,
            job_title=payload.job_title,
            actor_id=actor.user.id,
        )
        return self.to_out(user)

    async def update_user(
        self, actor: Principal, user_id: uuid.UUID, payload: UserUpdate
    ) -> UserOut:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFound("User not found")
        await self._require_manage(actor, target=user, role_key=None)
        if payload.status is not None and payload.status is not user.status:
            if payload.status is not UserStatus.ACTIVE:
                if user.id == actor.user.id:
                    raise PermissionDenied("You cannot suspend yourself")
                await self._ensure_not_last_super_admin(user)
            user.status = payload.status
        if payload.display_name is not None and user.staff_profile is not None:
            user.staff_profile.display_name = payload.display_name
        if payload.job_title is not None and user.staff_profile is not None:
            user.staff_profile.job_title = payload.job_title
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="user.updated",
            entity_type="user",
            entity_id=user.id,
            after=payload.model_dump(exclude_none=True, mode="json"),
        )
        await self.db.commit()
        return self.to_out(user)

    async def grant_role(
        self, actor: Principal, user_id: uuid.UUID, payload: RoleGrantCreate
    ) -> UserRoleOut:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFound("User not found")
        if user.kind is not UserKind.STAFF:
            raise PermissionDenied("Roles can only be granted to staff")
        role = await self.db.scalar(select(Role).where(Role.key == payload.role_key))
        if role is None:
            raise NotFound(f"Unknown role '{payload.role_key}'")
        await self._require_manage(actor, target=user, role_key=role.key, role_rank=role.rank)
        grant = UserRole(
            user_id=user.id,
            role_id=role.id,
            section_id=payload.section_id,
            granted_by=actor.user.id,
            created_at=datetime.now(UTC),
        )
        self.db.add(grant)
        await self.db.flush()
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="user.role_granted",
            entity_type="user",
            entity_id=user.id,
            after={
                "role": role.key,
                "section_id": str(payload.section_id) if payload.section_id else None,
            },
        )
        await self.db.commit()
        return UserRoleOut(
            id=grant.id,
            role_key=role.key,
            section_id=grant.section_id,
            granted_by=grant.granted_by,
            created_at=grant.created_at,
        )

    async def revoke_role(
        self, actor: Principal, user_id: uuid.UUID, user_role_id: uuid.UUID
    ) -> None:
        grant = await self.db.get(UserRole, user_role_id)
        if grant is None or grant.user_id != user_id:
            raise NotFound("Role grant not found")
        user = await self.users.get(user_id)
        if user is None:
            raise NotFound("User not found")
        await self._require_manage(
            actor, target=user, role_key=grant.role.key, role_rank=grant.role.rank
        )
        if user.id == actor.user.id and grant.role.rank == actor.grants.max_rank:
            raise PermissionDenied("You cannot revoke your own highest role")
        if grant.role.key == SUPER_ADMIN_ROLE:
            await self._ensure_not_last_super_admin(user)
        await self.db.delete(grant)
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="user.role_revoked",
            entity_type="user",
            entity_id=user.id,
            before={"role": grant.role.key},
        )
        await self.db.commit()

    async def create_role(self, actor: Principal, payload: RoleCreate) -> RoleOut:
        self._require_role_manager(actor, payload.rank)
        if payload.key == SUPER_ADMIN_ROLE or payload.key in {
            "writer",
            "copy_editor",
            "editor",
            "admin",
        }:
            raise Conflict("That key is reserved for a system role")
        role = Role(
            id=uuid.uuid7(),
            key=payload.key,
            name=payload.name.strip(),
            description=payload.description,
            is_system=False,
            rank=payload.rank,
        )
        self.db.add(role)
        set_committed_value(role, "permissions", [])
        role.permissions = await self._permissions(payload.permissions)
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="role.created",
            entity_type="role",
            entity_id=role.id,
            after={"key": role.key, "rank": role.rank, "permissions": payload.permissions},
        )
        await self.db.commit()
        return self._role_out(role)

    async def update_role(
        self, actor: Principal, role_id: uuid.UUID, payload: RoleUpdate
    ) -> RoleOut:
        role = await self.db.scalar(
            select(Role).where(Role.id == role_id).options(selectinload(Role.permissions))
        )
        if role is None:
            raise NotFound("Role not found")
        if role.is_system:
            raise Conflict("System roles are defined in code")
        rank = payload.rank if payload.rank is not None else role.rank
        self._require_role_manager(actor, rank)
        if payload.name is not None:
            role.name = payload.name.strip()
        if payload.description is not None:
            role.description = payload.description
        if payload.rank is not None:
            role.rank = payload.rank
        if payload.permissions is not None:
            role.permissions = await self._permissions(payload.permissions)
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="role.updated",
            entity_type="role",
            entity_id=role.id,
            after={"key": role.key, "rank": role.rank},
        )
        await self.db.commit()
        return self._role_out(role)

    async def list_roles(self) -> list[RoleOut]:
        roles = (await self.db.scalars(select(Role).order_by(Role.rank))).all()
        return [self._role_out(role) for role in roles]

    def _require_role_manager(self, actor: Principal, rank: int) -> None:
        if not actor.grants.has_anywhere(Perm.ROLE_MANAGE):
            raise PermissionDenied("Missing permission: role.manage")
        if rank >= actor.grants.max_rank:
            raise PermissionDenied("A role must rank below your own")

    async def _permissions(self, codes: list[str]) -> list[Permission]:
        known = {item.value for item in Perm}
        unknown = [code for code in codes if code not in known]
        if unknown:
            raise Conflict(f"Unknown permission: {unknown[0]}")
        rows = list(
            (await self.db.scalars(select(Permission).where(Permission.code.in_(codes)))).all()
        )
        if len(rows) != len(set(codes)):
            raise Conflict("Unknown permission")
        return rows

    @staticmethod
    def _role_out(role: Role) -> RoleOut:
        return RoleOut(
            id=role.id,
            key=role.key,
            name=role.name,
            description=role.description,
            rank=role.rank,
            is_system=role.is_system,
            permissions=sorted(item.code for item in role.permissions),
        )

    async def _require_manage(
        self,
        actor: Principal,
        *,
        target: User | None,
        role_key: str | None,
        role_rank: int | None = None,
    ) -> None:
        if target is not None and target.id != actor.user.id:
            ensure_outranks(actor.grants, await DbAuthorizer(self.db).grants_for(target.id))
        if role_rank is not None:
            ensure_can_grant_role(actor.grants, role_rank)

    async def _ensure_not_last_super_admin(self, user: User) -> None:
        grants = await DbAuthorizer(self.db).grants_for(user.id)
        if SUPER_ADMIN_ROLE not in grants.role_keys:
            return
        others = await self.db.scalars(
            select(UserRole.user_id)
            .join(Role)
            .where(Role.key == SUPER_ADMIN_ROLE, UserRole.user_id != user.id)
        )
        if others.first() is None:
            raise PermissionDenied("The last super admin cannot be removed")

    async def register_reader(
        self, email: str, password: str, display_name: str | None, locale: str | None
    ) -> User:
        from newsroom.settings.service import SettingsService

        settings = await SettingsService(self.db).get()
        if not settings.registration_enabled:
            raise PermissionDenied("Registration is closed")
        email = normalize_email(email)
        if await self.users.get_by_email(email) is not None:
            raise EmailTaken(f"{email} is already registered")
        user = User(
            email=email,
            password_hash=hash_password(password),
            kind=UserKind.READER,
            status=UserStatus.ACTIVE,
            reader_profile=ReaderProfile(display_name=display_name, preferred_locale=locale),
        )
        self.users.add(user)
        await self.db.commit()
        return user

    async def update_reader_profile(
        self,
        user: User,
        *,
        display_name: str | None,
        preferred_locale: str | None,
        newsletter_opt_in: bool | None,
    ) -> User:
        profile = user.reader_profile
        if profile is None:
            raise NotFound("Reader profile not found")
        if display_name is not None:
            profile.display_name = display_name
        if preferred_locale is not None:
            profile.preferred_locale = preferred_locale
        if newsletter_opt_in is not None:
            profile.newsletter_opt_in = newsletter_opt_in
        await self.db.commit()
        return user
