"""Operational commands: ``uv run newsroom --help``."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Annotated

import typer
from sqlalchemy.ext.asyncio import AsyncSession

import newsroom.models  # noqa: F401  (registers every mapper)
from newsroom.auth.service import AuthService
from newsroom.authz.permissions import SUPER_ADMIN_ROLE
from newsroom.authz.seed import seed_rbac
from newsroom.core.config import get_settings
from newsroom.core.db import create_engine, create_sessionmaker
from newsroom.core.errors import AppError
from newsroom.locales.seed import seed_locales
from newsroom.seed.demo import seed_demo
from newsroom.seed.volume import seed_volume
from newsroom.users.repository import UserRepository
from newsroom.users.service import UserService

app = typer.Typer(no_args_is_help=True, add_completion=False)


def run_with_db[T](fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async def runner() -> T:
        engine = create_engine(get_settings())
        try:
            async with create_sessionmaker(engine)() as db:
                return await fn(db)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(runner())
    except AppError as exc:
        typer.secho(f"Error: {exc.detail or exc.code}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc


@app.command()
def seed() -> None:
    """Seed locales, roles, and demo accounts and stories (idempotent)."""

    async def job(db: AsyncSession) -> None:
        added = await seed_locales(db)
        result = await seed_rbac(db)
        typer.echo(f"locales added: {added}")
        typer.echo(f"permissions: {result.permissions}, system roles: {result.roles}")
        if result.removed_permissions:
            typer.echo(f"removed stale permissions: {', '.join(result.removed_permissions)}")
        for line in await seed_demo(db):
            typer.echo(line)
        for line in await seed_volume(db):
            typer.echo(line)

    run_with_db(job)


@app.command("create-superadmin")
def create_superadmin(
    email: Annotated[str, typer.Option(prompt=True)],
    display_name: Annotated[str, typer.Option(prompt=True)],
    password: Annotated[str, typer.Option(prompt=True, confirmation_prompt=True, hide_input=True)],
) -> None:
    """Create a staff user with the super_admin role."""
    if len(password) < 12:
        typer.secho("Password must be at least 12 characters", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    async def job(db: AsyncSession) -> None:
        user = await UserService(db).create_staff(
            email=email, display_name=display_name, password=password, role_key=SUPER_ADMIN_ROLE
        )
        typer.echo(f"created super admin {user.email} ({user.id})")

    run_with_db(job)


@app.command("create-api-token")
def create_api_token(
    email: Annotated[str, typer.Option(help="Staff user that owns the token")],
    name: Annotated[str, typer.Option(help="Label, e.g. 'ci-importer'")],
    days: Annotated[int, typer.Option(min=1, max=365)] = 90,
) -> None:
    """Issue a bearer token for a staff user. The token is shown once."""

    async def job(db: AsyncSession) -> None:
        user = await UserRepository(db).get_by_email(email)
        if user is None:
            typer.secho(f"No user {email}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
        issued = await AuthService(db, get_settings()).create_api_token(
            user, name, timedelta(days=days)
        )
        typer.echo(issued.token)

    run_with_db(job)


if __name__ == "__main__":
    app()
