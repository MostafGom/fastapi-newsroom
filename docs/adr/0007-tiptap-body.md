# ADR 0007 — TipTap JSON as the article body

Status: accepted

## Context
Articles need a rich-text editor: headings, lists, quotes, links, inline images. The public
site must not trust HTML sent by the browser. Arabic and English are both edited, sometimes
on the same screen as a dashboard in the other language.

## Decision
- The editor is [TipTap](https://tiptap.dev/) (ProseMirror).
- The stored source of truth is the TipTap document (`body` jsonb on each revision).
- The server renders that document to HTML with an allowlist of nodes (paragraph, heading
  levels 2–4, lists, quote, code, link, image, horizontal rule). The article title is a
  separate field, so the body has no H1.
- Rendered HTML is passed through `nh3` with the same allowlist. Unknown nodes are rejected
  at save time, not stripped silently.
- The editor's `dir` follows the localization being edited, not the dashboard language.

## Consequences
- A new mark or block is a code change in both the editor extensions and `articles/body.py`.
- Clients that only have the JSON can re-open the story. Clients that only have the HTML
  cannot. The public site uses the rendered HTML.
- Images in the body point at our media URLs. The media slice will reject anything else.
