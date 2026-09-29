# ADR 0006 — Per-locale publishable units with immutable revisions

Status: accepted

## Context
Articles must support Arabic and English at launch, with more locales later. Each language
version may be published at a different time. Every saved version must be viewable and restorable.

## Decision
- `articles` holds language-neutral data: section, bylines, tags, lead media, type.
- `article_localizations` is the publishable unit. It holds status, slug, schedule, and two
  pointers: `current_revision_id` (the working copy) and `published_revision_id` (the live copy).
- `article_revisions` rows are immutable snapshots of the translatable content.
- `locales` is a table, so adding a language is an `INSERT`.

## Alternatives rejected
- **JSONB column with all languages in one row**: easy to start with, but per-language
  status, slugs and uniqueness constraints become application logic, and indexes get awkward.
- **One article row per language, loosely linked**: loses shared metadata and makes
  "this is the English version of that story" implicit.
- **Mutable article row plus a history table written by triggers**: history becomes secondary
  and restores become updates that rewrite the present.

## Consequences
- Reads of a live article join localization → published revision. This is one indexed join.
- Editing a live article is safe by construction: the live pointer only moves on `publish_update`.
- Storage grows with every save. Autosave coalescing keeps it bounded, and old autosaves can be
  pruned without touching manual revisions.
