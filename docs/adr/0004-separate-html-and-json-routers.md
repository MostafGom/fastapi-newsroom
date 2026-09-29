# ADR 0004 — Separate HTML and JSON routers over one service layer

Status: accepted

## Context
The application serves Jinja pages (public site and dashboard, enhanced with HTMX and Alpine)
and a JSON API. One option is a single route that switches on `Accept`. The other is
separate routers.

## Decision
- JSON lives under `/api/v1` (public) and `/api/v1/admin` (staff).
- HTML lives under `/{locale}/...` (public) and `/admin/...` (staff).
- Both call the same services. HTML routes never call the API over HTTP.
- HTMX requests hit the HTML routes. The `HX-Request` header selects a fragment template instead of the full page.

## Consequences
- Each side has its own concerns: status codes and Pydantic models for JSON, redirects, flash
  messages and templates for HTML. Neither side gets bent to fit the other.
- OpenAPI documents only the JSON API, which keeps it clean.
- Business rules exist once, in services. Routes stay thin: parse the input, call the service,
  render the result.
- Some duplication in route signatures is accepted as the price of that control.
