# Working agreement

Read this file before changing the newsroom. The domain contract is in `docs/`. This file is how to run the project and how to change it without breaking the rules already settled.

Check `git status` before editing. Do not assume the tree is clean, and do not revert unrelated work.

## Environment

- Python 3.14, [uv](https://docs.astral.sh/uv/), FastAPI, SQLAlchemy 2.1 async + asyncpg, Alembic, Pydantic 2, pwdlib Argon2id, nh3, Pillow, structlog.
- HTML: Jinja, HTMX, Alpine. Article body: TipTap JSON, rendered on the server. Styles: Tailwind v4, built by Vite in `frontend/`.
- PostgreSQL 18 on the host, port **5433 only**. Role `newsroom` owns databases `newsroom` (app) and `newsroom_test` (pytest). Never point tests at the app database.
- Copy `.env.example` to `.env`. Never commit `.env`, credentials, or media files. `SECRET_KEY` and database passwords stay in the environment.
- Generated browser files live in `src/newsroom/static/dist/` and are gitignored. After a template class, CSS, or editor change, run `cd frontend && npm run build`.
- Locales at launch: Arabic (default, RTL) and English. UI strings are `src/newsroom/messages/ar.json` and `en.json`. The desk renders in the staff member's preferred locale, Arabic unless that preference is English.

## Start, seed, test

From the `newsroom/` directory:

```bash
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run newsroom seed
uv run uvicorn newsroom.asgi:app --reload    # http://127.0.0.1:8000
```

Do not start a second web server if one is already listening on port 8000.

The worker publishes scheduled stories and sends the daily briefing. Start it only when that behavior is what you are working on, and do not leave it running:

```bash
uv run python -m newsroom.worker
```

`newsroom seed` is idempotent. It creates locales, roles, demo accounts, three workflow fixtures, and about 100 extra published briefs (200 localizations) for the **dev** database. A second run does not duplicate them.

Demo password for every `demo-*` account: `demo-password-123`.

| Email | Role |
|---|---|
| `demo-super@example.com` | Super admin |
| `demo-editor@example.com` | Editor, politics desk only |
| `demo-copy@example.com` | Copy editor |
| `demo-writer@example.com` | Writer |
| `demo-reader@example.com` | Reader |

Staff sign in at `/admin/login`. Readers sign in at `/ar/login` or `/en/login`. A staff email on the reader form fails with the same message as a wrong password. An existing super admin such as `admin@example.com` is not reset by seed.

Tests:

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
uv run pyright
```

Pytest drops and migrates `newsroom_test`, seeds locales and roles, then rolls each test back. `seed_demo` (the three fixture stories) is what tests call. `seed_volume` (the 100 briefs) is only invoked by the `newsroom seed` command. Do not call `seed_volume` from tests: search and home-page assertions depend on the small fixture.

## What is built

Phases 1–3 are in the application. Read `docs/01-scope.md` through `docs/06-editorial-scenarios.md` and `docs/adr/` before changing the model.

Settled behavior:

- One FastAPI app. HTML routers and JSON routers call the same services. HTML never calls the JSON API over HTTP.
- One `users` table. `kind` is `staff` or `reader`. Sessions are opaque server-side tokens, not JWT. Staff cookie `nr_staff` (12 hours). Reader cookie `nr_session` (30 days). No staff 2FA in this version.
- In-house RBAC. Route dependencies are the coarse check. Services enforce section scope, ownership, and workflow state.
- Each language of a story has its own status, slug, and published revision. Revisions are immutable. Restoring copies an old revision into a new one.
- Published text is never hard-deleted. Takedown is a status. Legal purge is the only hard delete, and it writes the audit row first.
- Public search is Postgres full-text in `newsroom.search`, over **published** localizations only. Drafts are not in that index. Typo tolerance is later, behind the same service, not inside `ArticleService`.
- Media bytes are stored under `MEDIA_DIR` as `{uuid}.{ext}` plus a display JPEG. The UUID is the public address (`/media/{id}`). A human filename is a separate column and must never become the path.
- The public site is a newspaper: self-hosted Newsreader and Noto Naskh for reading, IBM Plex for the desk, square controls, red only for the masthead, kickers, corrections, and destructive actions.

## What is not done

Do this next, in this order, unless the user says otherwise.

1. **Desk search.** Do not put stories, accounts, and the audit log in one box. Add a story search that includes drafts (the public index cannot do that), plus a text filter on each list that already has a natural key: email on accounts, key or name on tags, sections, and bylines, filename on media.

Still out of scope until the user asks: Meilisearch or typo-tolerant search, a comment moderation queue, a paywall, newsletter unsubscribe, staff 2FA, a dark theme.

## How to change the code

- Routes parse input, call a service, and render. Services own the transaction and write the audit event in that same transaction.
- Schema changes go through Alembic. Review an autogenerate diff before keeping it. Register new models in `src/newsroom/models.py`.
- Match the module you are in: `models`, `schemas`, `repository`, `service`, then a thin router.
- Add both Arabic and English UI strings. Arabic is modern standard Arabic, not a word-for-word translation of the English.
- A feature is not done without a test. Extend `tests/integration/` for HTTP and database behavior, `tests/unit/` for pure logic. Assert the new rule, including the denial (wrong role, wrong audience, stale `lock_version`, missing CSRF).
- Run the relevant pytest file and `ruff check` on the files you touched. Do not commit or push unless the user asks. Never add `Co-authored-by` or other tool attribution to a commit.

## Security

Treat these as mandatory on any action that changes data, grants access, or deletes something:

- Authorize in the service with the loaded entity. A route dependency is not enough for section scope or ownership.
- Staff and reader logins stay separate. Do not accept a reader session on a staff route, or the reverse.
- Cookie-authenticated POST, PUT, PATCH, and DELETE require the CSRF token. Bearer tokens do not.
- Passwords stay Argon2id. Do not log secrets, session tokens, or password fields.
- Rendered article HTML goes through `nh3`. Do not mark unsanitized body HTML as safe.
- Store uploads by a generated id. Reject path segments in a display name. Cap upload size and sniff the type; do not trust the browser's content type.
- Optimistic concurrency: stale `lock_version` or `base_revision_id` returns 409. Do not overwrite.
- Destructive or privileged actions (publish, unpublish, purge, role grant, user status, media delete) write an audit event in the same transaction as the change. Purge is super-admin only.
- Do not add a back door, a default password, or a way to skip CSRF or permission checks for local development.
