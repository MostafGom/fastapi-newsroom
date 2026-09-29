# ADR 0008 — Vite build for Tailwind, HTMX, Alpine and TipTap

Status: accepted

## Context
The pages are server-rendered Jinja. They still need three browser dependencies: Tailwind
for styling, HTMX and Alpine for behaviour, and TipTap for the editor. TipTap is a set of
ES modules, so it cannot be dropped in as one file without a bundler. Tailwind v4 has an
official Vite plugin, so one build covers CSS and JS.

## Decision
`frontend/` is a small Node project. `npm run build` writes hashed-name-free files to
`src/newsroom/static/dist/` (`app.js`, `app.css`). Jinja loads only those two files.
The Python app does not run Node at request time.

`npm run dev` rebuilds on change. Docker runs the same build in a Node stage and copies
`dist/` into the Python image.

## Consequences
- Changing a template class, a stylesheet, or the editor requires a rebuild before it
  shows up. Tailwind only emits classes it can see in `src/newsroom/templates` and
  `frontend/src`.
- `dist/` is generated and gitignored. A fresh clone needs Node once, or a Docker build.
- HTMX and Alpine are no longer vendored by hand.
