---
name: desk-ui
description: >
  Build and change newsroom HTML so it matches the existing newspaper desk.
  Use when editing Jinja templates, admin or public pages, Tailwind classes,
  or frontend/src/main.css. Covers filters, cards, lists, forms, RTL Arabic,
  and the paper, ink, and accent tokens.
paths:
  - newsroom/src/newsroom/templates/**
  - newsroom/frontend/src/**
  - src/newsroom/templates/**
  - frontend/src/**
---

# Desk UI

The newsroom already has a visual system. Reuse it. Do not invent a second one for a new page.

Stack: Jinja, HTMX, Alpine, Tailwind v4. Styles live in `frontend/src/main.css` and are built by Vite. There is no React and no component library.

## Tokens

Use the variables in `@theme`. Do not add a palette or a type stack.

- Type: `--font-display` and `--font-text` are Newsreader and Noto Naskh Arabic. `--font-ui` is IBM Plex Sans and IBM Plex Sans Arabic. Public reading uses the serif. Desk chrome uses the sans.
- Color: `--color-ink`, `--color-paper`, `--color-card`, `--color-line`, `--color-muted`. `--color-accent` is only for the masthead, kickers, corrections, and destructive actions.
- Corners stay square. Controls are not pills.

## Compose these classes

Read `frontend/src/main.css` before adding a class. Prefer a class that already exists.

- Page title row: `.panel-head`, with `.lede` under the heading and `.btn-line` for the action.
- Filters: `.form` or `.form-row`, each control in `.field`, submit with `.btn-line`. A filter form that needs the full column uses `.form-wide`. See `admin/users.html`.
- Grouped desk content: `.panel`. Link grids: `.area-grid`.
- Public story lists: `.story-list` and `.story-card` (`.story-body`, `.headline`, `.deck`, `.meta`, `.kicker`, `.story-foot`).
- The desk column is `.desk-content` (`max-width: 64rem`) beside a 16rem nav. A wide table overflows it, especially in Arabic RTL. Use a card or a stacked row of facts.

If a layout is used twice and no class fits, add one next to its relatives in `main.css`, using the tokens above. Do not leave a page styled only with one-off utilities such as `text-2xl font-bold`, `border-b`, or `text-sm text-muted`.

## Arabic and copy

The desk is Arabic and RTL unless the staff member prefers English. Use logical properties (`inline`, `block`) rather than left and right. Add every new string to `src/newsroom/messages/ar.json` and `en.json` together. Arabic is modern standard Arabic.

## After a style change

From `newsroom/`:

```bash
cd frontend && npm run build
```

Generated files in `src/newsroom/static/dist/` are gitignored. A template class that is not in the built CSS does not appear in the browser.
