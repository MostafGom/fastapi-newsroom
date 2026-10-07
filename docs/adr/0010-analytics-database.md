# ADR 0010 — Analytics in a second Postgres database

Status: accepted

## Context

The desk needs visits, unique visitors, engaged time, scroll depth, and explicit clicks for
the public site and for each published localization. Comments and bookmarks are already
exact rows in the editorial database.

Those traffic events are append-only and safe to delay or drop. Putting them on
`article_localizations`, or in the same database as publishing, would mix a high-volume
log with the desk's transactions, backups, and vacuum.

The measures the desk shows are fixed: today, 7 days, and 28 days. They do not require
scanning raw events on each page load.

## Decision

`newsroom_analytics` is a second PostgreSQL 18 database on the same server as `newsroom`.
It has its own connection pool and its own Alembic history (`migrations_analytics/`).
No extension is installed. Native daily partitions, a BRIN index on event time, and
B-tree keys on the rollup tables are enough.

`newsroom.analytics` is the only module that writes that database. The collect endpoint
never opens an editorial transaction. The desk reads rollup rows, then loads titles,
comment counts, and bookmark counts from the editorial database and combines them in
Python. There is no cross-database join.

Raw events are kept for 90 days. The worker rebuilds the open hour, the current day, and
the 1-, 7-, and 28-day windows. Unique visitors are counted inside those rollups.
The admin screens read the rollups only.

Comments and bookmarks stay in the editorial database. They are not copied into events.

A JavaScript beacon records a view. A signed page token carries the localization, section,
and page ids, so the browser cannot name an arbitrary story. A staff session cookie is
ignored. The visitor id is a random first-party cookie, not a user id.

ClickHouse or TimescaleDB replaces the event store later, behind the same repository,
if a day no longer aggregates inside the worker interval or the desk needs ad-hoc scans
of raw history. Not before.

## Consequences

- Operators create `newsroom_analytics` and `newsroom_analytics_test` and run
  `alembic -c alembic_analytics.ini upgrade head` as well as the editorial migrations.
- A failed analytics write does not fail the public page. The collect handler answers
  `204` and drops the batch.
- A failed analytics read does not take down the rest of the desk. The panel says the
  numbers are unavailable.
- Seven-day and 28-day uniques are exact for one section or the whole site. Summing two
  sections can count one visitor twice. Editors are scoped to one section; admins see
  the site-wide row.
