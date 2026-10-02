# Newsroom

Multilingual news publishing platform with a public site for readers, an editorial dashboard
for staff, and a JSON API, all served by one FastAPI application.

Agents continuing this work should read [AGENTS.md](AGENTS.md) first, then `docs/`.

- **Backend**: FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic, Pydantic v2
- **Frontend**: Jinja templates + HTMX (server interaction) + Alpine.js (local UI state)
- **Database**: PostgreSQL 18
- **Languages**: Arabic (RTL, default) and English at launch. Locales are data, so adding one needs no migration.

## Design

Read these before changing the domain model:

| Doc | Content |
|---|---|
| [docs/01-scope.md](docs/01-scope.md) | Actors, requirements, phases |
| [docs/02-schema.md](docs/02-schema.md) | ERD and table definitions |
| [docs/03-authz.md](docs/03-authz.md) | Sessions, CSRF, permission codes, role matrix, policies |
| [docs/04-workflow.md](docs/04-workflow.md) | Article state machine, revisions, audit, scheduler |
| [docs/05-api-contract.md](docs/05-api-contract.md) | Routes, conventions, status codes |
| [docs/adr/](docs/adr/) | Architecture decisions and their trade-offs |

The live API contract is at `/api/docs` once the server runs.

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). Postgres runs locally on port **5433**.

```bash
uv sync
cp .env.example .env          # fill in DATABASE_URL, TEST_DATABASE_URL, SECRET_KEY

uv run alembic upgrade head   # schema
uv run newsroom seed          # locales, roles, demo accounts and stories (idempotent)
uv run newsroom create-superadmin  # optional; seed already includes a demo super admin

uv run uvicorn newsroom.asgi:app --reload      # http://localhost:8000
uv run python -m newsroom.worker               # background jobs (separate process)
```

### Styles and scripts

Jinja renders the HTML. The browser assets are built separately, once, into two files the
templates load: `src/newsroom/static/dist/app.css` and `app.js`.

```
frontend/src/main.css    Tailwind v4  →  dist/app.css
frontend/src/main.js     HTMX, Alpine, CSRF
frontend/src/editor.js   TipTap       →  loaded only on pages that contain the editor
        │
        │  npm run build   (Vite)
        ▼
src/newsroom/static/dist/
```

Tailwind scans `src/newsroom/templates` and `frontend/src`. A class that exists in neither
place is not in the CSS file. After changing a template class, the stylesheet, or the editor:

```bash
cd frontend && npm install && npm run build
```

`npm run dev` rebuilds on save. The Python process does not run Node. Docker runs this
build in a Node stage and copies `dist/` into the image, so production does not need Node
either. `dist/` is generated and not committed.

The article body is TipTap JSON. The server turns it into HTML (`articles/body.py`) and
runs it through `nh3`. `/admin/editor` previews a body without saving it. The desk is `/admin/`:
new stories at `/admin/stories/new`, revisions and workflow actions on
`/admin/stories/{id}`. The same operations are on the admin JSON API.

There is no staff two-factor authentication in this version. Staff sessions last 12 hours
and can be revoked immediately.

- Public site: `/ar/`, `/en/`. Readers sign in at `/{locale}/login` and manage their profile and bookmarks at `/{locale}/account`.
- Dashboard: `/admin/`
- API docs: `/api/docs`

### Demo accounts

`newsroom seed` creates these when they are missing. The password for every demo account is `demo-password-123`.

| Email | What they can do |
|---|---|
| `demo-super@example.com` | Super admin |
| `demo-editor@example.com` | Editor on the politics desk |
| `demo-editor-sports@example.com` | Editor on the sports desk |
| `demo-editor-economy@example.com` | Editor on the economy desk |
| `demo-editor-science@example.com` | Editor on the science desk |
| `demo-editor-culture@example.com` | Editor on the culture desk |
| `demo-copy@example.com` | Copy editor |
| `demo-writer@example.com` | Writer on the politics desk |
| `demo-writer-sports@example.com` | Writer on the sports desk |
| `demo-writer-economy@example.com` | Writer on the economy desk |
| `demo-writer-science@example.com` | Writer on the science desk |
| `demo-writer-culture@example.com` | Writer on the culture desk |
| `demo-reader@example.com` | Reader: profile, bookmarks, and comments |
| `demo-reader-yusuf@example.com` | Reader |
| `demo-reader-sara@example.com` | Reader |
| `demo-reader-leila@example.com` | Reader |
| `demo-reader-fadi@example.com` | Reader |
| `demo-reader-huda@example.com` | Reader |

The same command publishes one fixture story in Arabic and English, leaves one story in review, and schedules one to publish six hours later. It then publishes about 100 original demo briefs (Arabic and English) across five desks so the dev lists are long enough to page. Those briefs are not copied from another publication. Running the command again does not duplicate accounts or stories. Tests call only the three fixtures, not the extra briefs. An existing super admin such as `admin@example.com` is left unchanged. Staff accounts sign in at `/admin/login`. The reader account signs in at `/ar/login` or `/en/login`.

### Database role (one-time)

```sql
CREATE ROLE newsroom LOGIN PASSWORD '...';
CREATE DATABASE newsroom OWNER newsroom;
CREATE DATABASE newsroom_test OWNER newsroom;
```

### Docker

`docker compose up --build` runs migrations, then the web app and worker, against the database
set in `DOCKER_DATABASE_URL` (see `.env.example`). Add `--profile db` to also start a bundled
Postgres for a clean clone.

## Commands

| Command | Purpose |
|---|---|
| `uv run pytest` | Tests (uses `TEST_DATABASE_URL`, rebuilt from migrations on every run) |
| `uv run ruff check . && uv run ruff format .` | Lint and format |
| `uv run pyright` | Type check |
| `uv run alembic revision --autogenerate -m "..."` | New migration (review it before committing) |
| `uv run newsroom create-api-token --email ... --name ...` | Bearer token for a staff user |

## Layout

```
src/newsroom/
  core/        config, db, errors (problem+json), logging, middleware, i18n, security
  auth/        sessions, login/logout, CSRF, principal resolution
  authz/       permissions + roles (code), grants (DB), Authorizer, policies, route guards
  users/ locales/ taxonomy/ articles/ audit/   feature modules: models, schemas, repository, service
  api/v1/      JSON routers (public, auth, admin)
  web/         HTML routers (public, admin) + Jinja setup
  templates/ static/ messages/   UI, vendored htmx/alpine, ar/en UI strings
  worker/      background job loop
migrations/    Alembic
tests/         unit/ (pure logic) and integration/ (HTTP + DB, rolled back per test)
```

Routes are thin. They parse input, call a service, and render JSON or HTML. Services own
transactions and write audit events in the same transaction as the change.

## Status

Phases 1–3 are in the application: identity and the desk, the public site, search,
media, site pages, the daily briefing, and reader comments.

Cursor pagination covers reader search, section and tag lists, and the home page,
which lists published stories by date. On the desk it covers the story list, the media
library, accounts, tags, and the audit log. Site pages are one list. The JSON API keeps
the opaque cursor. HTML lists use `?page=2` and append the next page in place, with
previous and next on that same page. Languages and roles stay one page. Desk search
is not built. The public search index covers published stories only.

Still deliberately out of this version: a comment moderation queue, a paywall, staff
two-factor authentication, and a second search engine for typo tolerance.
