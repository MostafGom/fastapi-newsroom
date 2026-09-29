# 05 — API and Route Contract

The machine-readable contract is the OpenAPI document FastAPI generates from the Pydantic
schemas and routers (`/api/docs`, `/api/openapi.json`). Routes that are not implemented yet
exist as stubs returning `501 Not Implemented`, so the contract is visible and testable from
day one. This file is the human-readable summary.

## Route families

| Prefix | Audience | Format | Auth |
|---|---|---|---|
| `/api/v1/...` | public clients, SPA/mobile later | JSON | optional reader session or bearer token |
| `/api/v1/admin/...` | staff tooling | JSON | staff session or staff bearer token |
| `/{locale}/...` | readers | HTML | optional reader session |
| `/admin/...` | staff dashboard | HTML (+ HTMX partials) | staff session |
| `/healthz`, `/readyz` | infrastructure | JSON | none |

HTML and JSON routers are separate modules that call the same services. HTML routes never call
the JSON API over HTTP.

## Conventions

- **Errors**: RFC 9457 `application/problem+json`:
  ```json
  {"type": "about:blank", "title": "Conflict", "status": 409,
   "detail": "Revision is stale", "code": "revision_conflict",
   "instance": "/api/v1/admin/localizations/…/revisions", "request_id": "…",
   "errors": [{"loc": ["body", "title"], "msg": "…"}]}
  ```
  `code` is a stable machine-readable string. `errors` appears only on validation failures (422).
- **Pagination**: cursor-based. Request `?limit=20&cursor=<opaque>`; response
  `{"items": [...], "next_cursor": "…" | null}`. `limit` is 1–100.
- **Locale**: the API selects it with `?locale=ar`, falling back to `Accept-Language`, then the
  default locale. HTML uses the URL prefix `/ar/...` or `/en/...`.
- **IDs**: UUID strings. **Timestamps**: ISO 8601 UTC with a `Z` suffix.
- **Concurrency**: revision saves send `base_revision_id`; metadata updates send `lock_version`.
  A stale value returns `409` with `code = "revision_conflict"` or `"version_conflict"`.
- **Status codes**:
  - `200` read or update
  - `201` create (with `Location`)
  - `204` delete or logout
  - `400` malformed request
  - `401` unauthenticated
  - `403` forbidden
  - `404` not found
  - `409` conflict or illegal transition
  - `410` gone (unpublished)
  - `422` validation
  - `429` rate limited
  - `501` stub

## Public JSON API (`/api/v1`)

| Method | Path | Purpose | Response |
|---|---|---|---|
| GET | `/locales` | Enabled locales | `LocaleOut[]` |
| GET | `/sections` | Section tree for a locale | `SectionOut[]` |
| GET | `/articles` | Published articles (`section`, `tag`, `limit`, `cursor`) | `Page[ArticleSummaryOut]` |
| GET | `/articles/{slug}` | Published article by slug in locale | `ArticleOut`; `301` if redirected slug; `410` if unpublished |
| GET | `/tags/{slug}/articles` | Articles by tag | `Page[ArticleSummaryOut]` |
| POST | `/auth/login` | Reader or staff login (`audience` field) | `SessionOut` + cookie |
| POST | `/auth/logout` | Revoke current session | `204` |
| GET | `/auth/me` | Current principal | `MeOut` |
| POST | `/auth/register` | Reader sign-up | `201 MeOut` |

## Admin JSON API (`/api/v1/admin`)

| Method | Path | Permission | Purpose |
|---|---|---|---|
| GET | `/articles` | `article.read` (or own) | Dashboard list, filters: `status`, `locale`, `section_id`, `author_id` |
| POST | `/articles` | `article.create` | Create article + first localization + first revision |
| GET | `/articles/{article_id}` | `article.read` (or own) | Article with all localizations |
| PATCH | `/articles/{article_id}` | `article.edit` (or own) | Language-neutral metadata (`lock_version`) |
| POST | `/articles/{article_id}/localizations` | `article.create` | Add a translation |
| GET | `/localizations/{localization_id}` | `article.read` (or own) | Localization with current revision |
| POST | `/localizations/{localization_id}/revisions` | `article.edit` / `article.edit_own` | Save (with `base_revision_id`) |
| GET | `/localizations/{localization_id}/revisions` | `article.read` (or own) | Revision list |
| GET | `/localizations/{localization_id}/revisions/{revision_id}` | `article.read` (or own) | One revision |
| GET | `/localizations/{localization_id}/revisions/{a}/diff/{b}` | `article.read` (or own) | Diff |
| POST | `/localizations/{localization_id}/revisions/{revision_id}/restore` | `article.restore_revision` | Restore |
| POST | `/localizations/{localization_id}/transitions` | per action (04-workflow) | `{action, reason?, publish_at?, lock_version}` |
| GET | `/localizations/{localization_id}/history` | `article.read` (or own) | Revisions + audit timeline |
| POST | `/localizations/{localization_id}/corrections` | `article.correct` | Add public correction |
| POST | `/localizations/{localization_id}/slug` | `article.edit` after publication, otherwise edit or own | `{slug}`; a live story keeps a 301 from the old slug |
| DELETE | `/localizations/{localization_id}` | `article.delete_draft` | Soft delete (never-published only) |
| GET/POST | `/sections` | `section.manage` for POST | List/create sections |
| PATCH | `/sections/{section_id}` | `section.manage` | Update section + translations |
| GET/POST | `/tags` | `tag.manage` for POST | List/create tags |
| GET/POST | `/users` | `user.read` / `user.manage` | Staff and reader accounts |
| GET/PATCH | `/users/{user_id}` | `user.read` / `user.manage` | View/update, suspend |
| POST | `/users/{user_id}/roles` | `role.assign` | Grant `{role_key, section_id?}` |
| DELETE | `/users/{user_id}/roles/{user_role_id}` | `role.assign` | Revoke |
| GET | `/roles` | `user.read` | Roles with permissions |
| GET | `/audit-events` | `audit.read` | Filter by entity, actor, action, time |

Transition requests go through **one endpoint with an action field** instead of one endpoint per
action. The state machine then stays in one place, and the audit log records the action name
exactly as requested.

## HTML routes

| Path | Page |
|---|---|
| `/` | Redirect to `/{default_locale}/` |
| `/{locale}/` | Home |
| `/{locale}/section/{slug}` | Section listing |
| `/{locale}/tag/{slug}` | Tag listing |
| `/{locale}/article/{slug}` | Article page |
| `/{locale}/login`, `/{locale}/register`, `/{locale}/account` | Reader account |
| `/admin/login`, `/admin/logout` | Staff auth |
| `/admin/` | Dashboard |
| `/admin/articles`, `/admin/articles/{id}`, `/admin/localizations/{id}/edit` | Editorial |
| `/admin/sections`, `/admin/tags`, `/admin/users`, `/admin/audit` | Management |

HTMX requests (`HX-Request: true`) to the same URLs return only the relevant fragment.
