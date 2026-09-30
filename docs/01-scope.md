# 01 — Scope and Requirements

Newsroom is a multilingual news publishing platform: a public site for readers and an
editorial dashboard for staff, served by one FastAPI application that exposes both HTML
(Jinja + HTMX + Alpine) and JSON (`/api/v1`) interfaces over a shared service layer.

## Actors

| Actor | Where they work | Summary |
|---|---|---|
| Anonymous visitor | Public site, public API | Reads published articles, browses sections and tags. |
| Reader | Public site | Registered account. Profile, preferences; later bookmarks, newsletters, comments, subscriptions. |
| Writer | Admin dashboard | Drafts articles, submits for review, proposes updates to own published pieces. |
| Editor | Admin dashboard | Reviews, approves, schedules, publishes, takes down, corrects. Scoped to sections. |
| Admin | Admin dashboard | Everything editorial, plus sections, tags, locales, staff accounts, role assignment. |
| Super admin | Admin dashboard | Everything, plus system settings, admin accounts, legal purge, full audit log. |
| Scheduler worker | Background process | Publishes scheduled articles and expires embargoed ones. |

## Functional requirements

### Content
- Articles exist once as a language-neutral container and have one **localization** per locale.
- Arabic (RTL) and English (LTR) at launch; adding a locale is a data change, never a migration.
- Each localization has its own workflow status, slug, schedule and published revision, so one
  language can go live before another.
- Every save produces an immutable **revision**. Any revision can be viewed, diffed, and
  restored (restoring creates a new revision).
- Published content is never hard-deleted. Takedowns are a status (`unpublished`) with a reason.
- Public correction notes attach to a localization.
- Slug changes after publication keep the old URL working through a 301 redirect.
- Bylines reference `authors`, which may or may not be staff users (guests, wire agencies).
- Sections are hierarchical and translatable; tags are translatable.
- Media assets carry credit and per-locale caption/alt text.

### Workflow
- Desk flow: `draft → in_review → copy_editing → approved → scheduled/published`.
  An editor can skip copy for breaking news, with a reason. See [06-editorial-scenarios.md](06-editorial-scenarios.md).
- `published → unpublished → published` (take down / republish); `archived` as a terminal state.
- Scheduled publishing (`publish_at`) and embargo expiry (`unpublish_at`), executed by a worker.
- Concurrent edits are detected (optimistic concurrency) and rejected with `409 Conflict`.

### Accountability
- Every state-changing action writes an append-only audit event in the same transaction:
  who, what, when, before/after, reason, IP, request ID.

### Identity and access
- One identity table for everyone; staff and readers are separated by `kind`, profile tables,
  login routes, and session cookies.
- Role-based permissions stored in the database, optionally scoped to a section, combined
  with coded policies for ownership and state rules.

## Non-functional requirements
- PostgreSQL 18 (local instance on port **5433**).
- Structured JSON logs with request IDs.
- Consistent errors: RFC 9457 `application/problem+json` for the API, HTML error pages for web.
- Revocable server-side sessions; CSRF protection on cookie-authenticated unsafe requests.
- Every schema change goes through Alembic.
- The project runs from a clean clone with `uv sync` and `.env`.

## Phase plan

Phases 1–3 are implemented. [AGENTS.md](../AGENTS.md) is the working agreement for anyone continuing the code: how to run it, what is unfinished, and the rules for security and tests.

| Phase | Content |
|---|---|
| 1 | Design docs, API contract, scaffold, cross-cutting concerns, identity/RBAC/audit. |
| 2 | Staff auth and user management, sections and tags, articles, revisions, workflow, scheduler, public site, reader accounts. |
| 3 | Search (own service; see [ADR 0009](adr/0009-search-service.md)), media pipeline, homepage curation, newsletters, comments. |

Next work, not started: finish cursor pagination on the lists that still stop after the first page, then add desk search that can see drafts. Public search stays published-only.

## Explicitly out of scope for v1 (revisit later)
- Paywall and payment processing.
- Reader comments moderation queue.
- Live blogs.
- Multi-tenant (multiple publications on one install).
- Staff two-factor authentication. Sessions stay revocable with a 12-hour staff TTL.

## Settled for v1
- Body format: TipTap (ProseMirror) JSON, rendered to HTML on the server and checked with `nh3`.
  See [ADR 0007](adr/0007-tiptap-body.md).
- Styles and browser scripts: Tailwind CSS and a Vite build in `frontend/`. See
  [ADR 0008](adr/0008-frontend-build.md) and the README.
- Search, when Phase 3 starts, is a dedicated service. See
  [ADR 0009](adr/0009-search-service.md). PostgreSQL full-text is the first engine.

## Reader features in v1
Bookmarks, the daily briefing, and comments on a published story are in. A comment
moderation queue, a paywall, and typo-tolerant search are not.
