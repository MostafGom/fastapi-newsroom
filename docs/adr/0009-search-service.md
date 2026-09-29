# ADR 0009 — Search is its own service

Status: accepted

## Context

Phase 3 adds search. A news site's search is a small search engine: per-language text,
ranking, snippets, and filters (section, tag, date). Bolting `ILIKE` onto the article
list will not survive Arabic morphology, headline ranking, or a published-versus-draft
split.

The rest of the app already keeps routes thin and puts behaviour in services. Search has
to follow that, and the engine has to be replaceable without rewriting the pages.

## Decision

`newsroom.search` is a separate module. Public HTML and `/api/v1` both call `SearchService`.
`ArticleService` does not grow a search method.

The service speaks in documents and hits, not in SQL:

- A document is one **published localization**: locale, title, excerpt, plain text of the
  body, section, tags, bylines, `published_at`. Drafts and taken-down stories are not
  documents.
- A query is the reader's text plus structured filters. Filters are not stuffed into the
  query string parser.
- A hit is the localization id, rank, and a highlighted snippet. The template does not
  recompute highlights from raw HTML.

The first engine is PostgreSQL full-text, in the same database as the articles:

- One `tsvector` per locale, using the `arabic` configuration for Arabic and `english`
  for English. One configuration for both languages is wrong.
- A GIN index. Updates happen in the same transaction as publish, publish-update, and
  unpublish, so the public page and the index cannot disagree.
- `websearch_to_tsquery` for the query, `ts_rank_cd` for rank, `ts_headline` for the
  snippet.
- No leading-wildcard `LIKE`.

Pagination is by `(published_at, id)` after a rank threshold, not by an unstable rank
cursor.

A later engine (Meilisearch, Typesense, OpenSearch) replaces the repository behind
`SearchService` only. Routes, filters, and the hit shape stay. Move when we need typo
tolerance, facets at a size Postgres will not serve, or semantic search. Not before.

## Consequences

- Publish, update, and takedown must notify the search service in the same transaction
  while the engine is Postgres. An external engine needs an outbox instead of a direct
  write.
- Arabic ranking will be weaker than English until we add a dictionary or an external
  engine. The service boundary is what makes that change local.
- Search is Phase 3 work. This ADR only fixes the shape so Phase 2 does not paint us
  into a filter on the article table.
