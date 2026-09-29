# ADR 0001 — One identity table for readers and staff

Status: accepted

## Context
Readers and staff both log in, but they have different profiles, different entry points, and
very different privileges. The two options were one `users` table for everyone, or separate
`readers` and `staff` tables.

## Decision
One `users` table holds only the login identity (email, password hash, status, `kind`). Profile
data lives in `staff_profiles` and `reader_profiles` (1:1). Isolation is enforced at the edges:

- separate login routes (`/login` and `/admin/login`)
- separate session kinds and cookies (`nr_session` and `nr_staff`) with different TTL and SameSite
- staff endpoints reject reader sessions
- roles can only be granted to `kind = staff`

## Consequences
- One implementation of login, password reset, email verification, rate limiting and session revocation.
- Global email uniqueness comes for free.
- A staff member who also reads the site uses a separate reader account. This is intentional:
  it keeps the privileged identity out of the public attack surface.
- Every query that lists "users" must filter by `kind`. Repositories expose kind-specific methods.
- A leaked reader session can never reach the dashboard, because the session kind is checked,
  not only the user.
