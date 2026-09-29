# ADR 0002 — In-house RBAC with coded policies instead of Casbin

Status: accepted

## Context
The newsroom needs role-based access (writer, editor, admin, super admin), section scoping (desk
editors), ownership rules (writers edit their own drafts), and state rules (published content
cannot be deleted). Casbin was considered.

## Decision
- Grants are stored in our own tables: `roles`, `permissions`, `role_permissions`, and
  `user_roles` with an optional `section_id`.
- Ownership and state rules are Python functions in `authz/policies.py`.
- Both layers sit behind an `Authorizer` protocol:
  `has(principal, permission, section_id=None) -> bool`.

## Why not Casbin
- The hardest rules depend on the loaded entity (status, owner, `first_published_at`), and
  they would be written in Python even with Casbin.
- The admin UI for role management needs first-class tables anyway. With Casbin, those tables
  and the Casbin policy store become two sources of truth.
- Grants per request are one indexed query, cached for the request lifetime. That is simpler
  to reason about than an enforcer cache that must be invalidated across workers.

## Consequences
- Permission codes are a Python `StrEnum` (`authz/permissions.py`), synced into the database by
  `newsroom seed` (idempotent). System roles are reset to their code definition, stale codes are
  removed, and custom roles are left untouched.
- Swapping the grant layer for Casbin later only means implementing the `Authorizer` protocol.
