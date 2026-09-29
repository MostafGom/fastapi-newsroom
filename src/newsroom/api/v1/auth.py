from fastapi import APIRouter, Depends, Request, Response, status

from newsroom.auth.dependencies import (
    OptionalReader,
    OptionalStaff,
    SettingsDep,
    clear_session_cookie,
    csrf_protect,
    ensure_csrf_token,
    set_session_cookie,
)
from newsroom.auth.principal import Principal
from newsroom.auth.schemas import (
    Audience,
    GrantOut,
    LoginRequest,
    MeOut,
    RegisterRequest,
    SessionOut,
)
from newsroom.auth.service import AuthService
from newsroom.core.db import DbSession
from newsroom.core.errors import NotAuthenticated
from newsroom.core.schemas import PROBLEM_RESPONSES
from newsroom.users.service import UserService

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses=PROBLEM_RESPONSES,
    dependencies=[Depends(csrf_protect)],
)


def to_me(principal: Principal) -> MeOut:
    user = principal.user
    return MeOut(
        id=user.id,
        email=user.email,
        kind=user.kind,
        display_name=user.display_name,
        roles=[GrantOut(role=g.role_key, section_id=g.section_id) for g in principal.grants.items],
        permissions=sorted(principal.grants.all_permissions()),
    )


@router.post("/login", response_model=SessionOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
) -> SessionOut:
    issued = await AuthService(db, settings).login(
        payload.email,
        payload.password,
        payload.audience,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    set_session_cookie(
        response, settings, payload.audience, issued.token, issued.session.expires_at
    )
    return SessionOut(expires_at=issued.session.expires_at, csrf_token=ensure_csrf_token(request))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    staff: OptionalStaff,
    reader: OptionalReader,
) -> None:
    service = AuthService(db, settings)
    for principal, audience in ((staff, Audience.STAFF), (reader, Audience.READER)):
        if principal is not None:
            await service.logout(principal.session)
            clear_session_cookie(response, settings, audience)


@router.get("/me", response_model=MeOut)
async def me(staff: OptionalStaff, reader: OptionalReader) -> MeOut:
    principal = staff or reader
    if principal is None:
        raise NotAuthenticated("Login required")
    return to_me(principal)


@router.post("/register", response_model=MeOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession) -> MeOut:
    user = await UserService(db).register_reader(
        payload.email, payload.password, payload.display_name, payload.preferred_locale
    )
    return MeOut(id=user.id, email=user.email, kind=user.kind, display_name=user.display_name)
