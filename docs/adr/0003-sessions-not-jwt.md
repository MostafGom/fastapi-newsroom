# ADR 0003 — Opaque server-side sessions instead of JWT

Status: accepted

## Context
Staff accounts have publishing power. When someone leaves or a device is lost, access must end
immediately. JWTs are valid until they expire unless a denylist is added, and a denylist is a
session table under another name.

## Decision
- Sessions are random opaque tokens. The database stores only their SHA-256 hash, plus kind,
  expiry, last activity, IP and user agent.
- Browsers carry the token in an `HttpOnly` cookie. API clients use
  `Authorization: Bearer` with a `kind = api_token` row in the same table.
- CSRF uses a double-submit token for cookie-authenticated unsafe requests. Bearer requests are exempt.

## Consequences
- Revocation is instant: "log out all devices" is one `UPDATE`.
- Each authenticated request costs one indexed lookup by `token_hash`. `last_seen_at` is written
  at most once per minute.
- Stateless horizontal scaling still works because the database is the shared store.
