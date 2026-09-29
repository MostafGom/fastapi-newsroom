"""identity rbac audit

Revision ID: 0001
Revises:
Create Date: 2026-09-29 03:51:33.236873+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "locales",
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("native_name", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.Enum("ltr", "rtl", name="text_direction"), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_locales")),
    )
    op.create_index(
        "uq_locales_single_default",
        "locales",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_permissions")),
    )
    op.create_table(
        "roles",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rank", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("key", name=op.f("uq_roles_key")),
    )
    op.create_table(
        "sections",
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["sections.id"],
            name=op.f("fk_sections_parent_id_sections"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sections")),
        sa.UniqueConstraint("key", name=op.f("uq_sections_key")),
    )
    op.create_index(op.f("ix_sections_parent_id"), "sections", ["parent_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("kind", sa.Enum("reader", "staff", name="user_kind"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "active", "suspended", "deactivated", name="user_status"),
            nullable=False,
        ),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index("ix_users_kind_status", "users", ["kind", "status"], unique=False)
    op.create_table(
        "audit_events",
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_action", "audit_events", ["action", "occurred_at"], unique=False
    )
    op.create_index(
        "ix_audit_events_actor", "audit_events", ["actor_id", "occurred_at"], unique=False
    )
    op.create_index(
        "ix_audit_events_entity",
        "audit_events",
        ["entity_type", "entity_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "reader_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("preferred_locale", sa.String(length=10), nullable=True),
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "newsletter_opt_in", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["preferred_locale"],
            ["locales.code"],
            name=op.f("fk_reader_profiles_preferred_locale_locales"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_reader_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_reader_profiles")),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_code", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_code"],
            ["permissions.code"],
            name=op.f("fk_role_permissions_permission_code_permissions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_permissions_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_code", name=op.f("pk_role_permissions")),
    )
    op.create_table(
        "section_translations",
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["locale"], ["locales.code"], name=op.f("fk_section_translations_locale_locales")
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name=op.f("fk_section_translations_section_id_sections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_section_translations")),
        sa.UniqueConstraint("locale", "slug", name=op.f("uq_section_translations_locale_slug")),
        sa.UniqueConstraint(
            "section_id", "locale", name=op.f("uq_section_translations_section_id_locale")
        ),
    )
    op.create_table(
        "sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("reader_web", "staff_web", "api_token", name="session_kind"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False)
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "staff_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("job_title", sa.String(length=120), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("preferred_locale", sa.String(length=10), nullable=True),
        sa.ForeignKeyConstraint(
            ["preferred_locale"],
            ["locales.code"],
            name=op.f("fk_staff_profiles_preferred_locale_locales"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_staff_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_staff_profiles")),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=True),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name=op.f("fk_user_roles_granted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_user_roles_role_id_roles"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name=op.f("fk_user_roles_section_id_sections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_roles_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_roles")),
        sa.UniqueConstraint(
            "user_id",
            "role_id",
            "section_id",
            name=op.f("uq_user_roles_user_id_role_id_section_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(op.f("ix_user_roles_user_id"), "user_roles", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_roles_user_id"), table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_table("staff_profiles")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("section_translations")
    op.drop_table("role_permissions")
    op.drop_table("reader_profiles")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_index("ix_audit_events_actor", table_name="audit_events")
    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_users_kind_status", table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_sections_parent_id"), table_name="sections")
    op.drop_table("sections")
    op.drop_table("roles")
    op.drop_table("permissions")
    op.drop_index(
        "uq_locales_single_default", table_name="locales", postgresql_where=sa.text("is_default")
    )
    op.drop_table("locales")
    for enum_name in ("session_kind", "user_status", "user_kind", "text_direction"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
