# ADR 0005 — Postgres-polled worker for scheduled publishing

Status: accepted

## Context
Scheduled publishing must be reliable across restarts and safe with multiple app instances.
The options were an in-process scheduler (APScheduler), a broker-based queue (Celery/RQ plus
Redis), or polling Postgres.

## Decision
A separate process, `python -m newsroom.worker`, polls every 30 seconds and claims due rows
with `FOR UPDATE SKIP LOCKED`. Each row is published in its own transaction with an audit event.

## Consequences
- No extra infrastructure. The schedule lives with the data, so it survives restarts and deploys.
- Publishing can be up to one poll interval late (default 30s). That is acceptable for a newsroom,
  and the interval is configurable.
- An in-process scheduler would fire N times with N web workers. Keeping the worker separate avoids that.
- If background jobs grow (image processing, newsletters), a Postgres-backed queue such as
  `procrastinate` can replace the loop without adding Redis.
