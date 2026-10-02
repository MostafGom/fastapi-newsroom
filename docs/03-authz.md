# 03 — Authentication and Authorization

## Authentication

- One `users` table. `kind` separates `reader` and `staff`.
- Passwords are hashed with Argon2id (`pwdlib`). Hashes are upgraded on login when parameters change.
- Sessions are opaque random tokens (`secrets.token_urlsafe(32)`). Only the SHA-256 hash is stored.

| Session kind | Transport | Cookie | TTL | CSRF |
|---|---|---|---|---|
| `reader_web` | cookie `nr_session` | `Path=/`, `HttpOnly`, `SameSite=Lax`, `Secure` in prod | 30 days sliding | required on unsafe methods |
| `staff_web` | cookie `nr_staff` | `Path=/`, `HttpOnly`, `SameSite=Strict`, `Secure` in prod | 12 hours sliding | required on unsafe methods |
| `api_token` | `Authorization: Bearer <token>` | none | explicit expiry | not needed (no ambient credential) |

The staff cookie is scoped by name, not by `Path`, because the staff JSON API lives under
`/api/v1/admin` and must accept it too. Staff endpoints only accept a `staff_web` session or a
staff-owned `api_token`. A reader cookie never authenticates a staff endpoint.

**CSRF** uses a signed double-submit token: the server sets a `nr_csrf` cookie, templates place
the same value in a `<meta>` tag and in hidden form fields, and HTMX sends it as `X-CSRF-Token`.
Unsafe requests authenticated by a cookie must present a matching token.

## Authorization model

Two layers, both behind one `Authorizer` interface:

1. **Grants (data)** — roles hold permission codes; users hold roles, optionally scoped to a
   section (`user_roles.section_id`; NULL = global).
2. **Policies (code)** — ownership and state rules that a role table cannot express, in
   `authz/policies.py`. A policy always calls the grant check first, then narrows.

```
can(principal, "article.publish", section_id=S)
  → grant check: does any role of the user include article.publish globally or for S?
  → policy check: e.g. is the localization in a state that allows publishing?
```

Routes declare the coarse requirement with `Depends(require_permission("..."))`. Services
enforce the fine-grained policy because they have the loaded entity.

## Permission codes

| Code | Meaning |
|---|---|
| `article.create` | Create articles and localizations |
| `article.read` | View any article in scope in the dashboard (own articles are always visible) |
| `article.edit_own` | Edit own articles while in `draft` / `changes_requested`; propose updates to own published articles |
| `article.edit` | Edit any article in scope, in any non-archived state |
| `article.submit` | Submit for review |
| `article.review` | Request changes, approve |
| `article.publish` | Publish, schedule, cancel schedule, publish update, republish |
| `article.unpublish` | Take down a published article (reason required) |
| `article.archive` | Archive |
| `article.delete_draft` | Soft-delete a never-published localization (own, or any with `article.edit`) |
| `article.restore_revision` | Restore an older revision as the new working copy |
| `article.correct` | Add public correction notes |
| `article.purge` | Legal hard-removal (super admin only, reason required, audited) |
| `section.manage` | Create/update sections and their translations |
| `tag.manage` | Create/update/merge tags |
| `media.upload` | Upload media |
| `media.manage` | Edit/delete any media |
| `locale.manage` | Add/enable/disable locales |
| `user.read` | List/view staff and readers |
| `user.manage` | Create/suspend staff and readers below own rank |
| `role.assign` | Grant/revoke roles below own rank |
| `role.manage` | Define custom roles and their permissions |
| `audit.read` | Read the audit log |
| `settings.manage` | System settings |

## Role matrix

| Permission | writer | copy_editor | editor | admin | super_admin |
|---|:-:|:-:|:-:|:-:|:-:|
| article.create | ✓ |  | ✓ | ✓ | ✓ |
| article.read |  | ✓ | ✓ | ✓ | ✓ |
| article.edit_own | ✓ |  | ✓ | ✓ | ✓ |
| article.edit |  | ✓ | ✓ | ✓ | ✓ |
| article.submit | ✓ |  | ✓ | ✓ | ✓ |
| article.copy |  | ✓ | ✓ | ✓ | ✓ |
| article.review |  |  | ✓ | ✓ | ✓ |
| article.clear_legal |  |  | ✓ | ✓ | ✓ |
| article.publish |  |  | ✓ | ✓ | ✓ |
| article.unpublish |  |  | ✓ | ✓ | ✓ |
| article.archive |  |  |  | ✓ | ✓ |
| article.delete_draft | ✓ |  | ✓ | ✓ | ✓ |
| article.restore_revision |  |  | ✓ | ✓ | ✓ |
| article.correct |  |  | ✓ | ✓ | ✓ |
| article.purge |  |  |  |  | ✓ |
| section.manage |  |  |  | ✓ | ✓ |
| tag.manage |  |  | ✓ | ✓ | ✓ |
| media.upload | ✓ | ✓ | ✓ | ✓ | ✓ |
| media.manage |  |  | ✓ | ✓ | ✓ |
| locale.manage |  |  |  | ✓ | ✓ |
| user.read |  |  |  | ✓ | ✓ |
| user.manage |  |  |  | ✓ | ✓ |
| role.assign |  |  |  | ✓ | ✓ |
| role.manage |  |  |  |  | ✓ |
| audit.read |  |  |  | ✓ | ✓ |
| settings.manage |  |  |  |  | ✓ |

Rank: writer 10, copy_editor 15, editor 20, admin 30, super_admin 100.

Editors are normally granted with a `section_id` (desk editor). A global editor grant makes a
managing editor. A copy editor is usually global (one copy desk) or scoped to the sections they
read. Translator and editor-in-chief, if added later, are new rows plus a permission selection.

## Policies worth stating explicitly

- **Rank rule**: an actor can manage a user or grant a role only if the actor's highest rank is
  strictly greater than the target's highest rank and the role's rank. Admins therefore cannot
  touch super admins or other admins; only super admins manage admins.
- **Last super admin** cannot be demoted, suspended, or deactivated.
- **Staff only**: roles can only be granted to `kind = staff` users.
- **Writers and the desk**: a writer edits their own story only in `draft` and
  `changes_requested`. While it is `in_review` or `copy_editing`, the desk owns the text.
  They can withdraw from review back to draft. On a live story they may save a proposal;
  it does not replace the published revision until an editor runs `publish_update`.
- **Copy editors do not publish.** They sign off language (`finish_copy`) or send the story
  back (`return_to_writer`). Skipping the copy desk is an editor action (`approve`) and
  requires a reason, which is how breaking news goes out.
- **Kill is not delete.** An editor spikes a story that has never been published
  (`killed`, reason required). It stays in the database. `delete` is only for a writer's
  own draft that never went live. Published stories are taken down (`unpublished`), never killed.
- **Legal hold** is a flag, not a status (`legal_hold` on the localization, added with the
  articles tables). Schedule, publish, and republish are refused while it is set, until someone with
  `article.clear_legal` records that counsel signed off. The lawyer is not a user of this app.
- **No hard deletes of published content** for any role except `article.purge`, which is
  reason-mandatory and still leaves an audit event with the removed identifiers.
- **No second factor in v1.** Staff sessions last 12 hours, are revocable, and use a
  separate cookie from reader sessions.
- **Self-protection**: nobody can revoke their own highest role or suspend themselves.

## Why not Casbin (summary; full record in ADR 0002)

Casbin's RBAC-with-domains maps well to grants, but our hardest rules depend on entity state
and ownership, which would live in Python anyway. We would also still need our own tables to
build the role-management UI, and we would keep two sources of truth in sync. The `Authorizer`
protocol keeps the door open to swap the grant layer for Casbin later.
