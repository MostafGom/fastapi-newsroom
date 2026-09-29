# 06 — Editorial scenarios

These are the situations the workflow is built for. Each one names who acts, which transition
fires, and what readers see. The state machine is in [04-workflow.md](04-workflow.md).

Roles in play: **writer**, **copy editor** (language, headlines, style; cannot publish),
**editor** (desk; usually scoped to a section such as politics), **admin**.

## 1. Ordinary story

The politics writer files a draft and submits it.

1. Writer: `submit` → `in_review`.
2. Politics editor reads it, accepts the story: `send_to_copy` → `copy_editing`.
3. Copy editor fixes the headline and a date, then `finish_copy` → `approved`.
4. Editor sets 06:00: `schedule`. The worker publishes it. Readers see that revision only.

The writer cannot edit the text while it sits with the desk or the copy editor. If they
withdraw (`in_review` → `draft`) they can. Once it is on the copy desk, only the desk can
send it back.

## 2. Desk sends it back

The editor thinks a quote is unsourced.

- From `in_review`: `request_changes` with the note "who said this?".
- Writer edits and `submit`s again.

The copy editor does the same from `copy_editing` with `return_to_writer` (a reason is
required). That is a language or structure problem, not a news-judgment problem, and it
uses `article.copy` so a copy editor never needs publish rights.

## 3. Breaking news, copy desk skipped

A ruling lands during a live session. Waiting for the copy desk would miss it.

- Editor: `approve` from `in_review`, reason "breaking, copy to follow".
- Editor: `publish`.
- The reason is on the audit event. Copy can still be done afterwards as a normal
  `publish_update` once a copy editor has saved a cleaned revision.

`approve` always requires a reason, because the only thing it does is skip copy.

## 4. Embargo

A ministry hands over a report for 18:00.

- Story is `approved` (copy already done).
- Editor: `schedule` with `publish_at` 18:00, and optionally `unpublish_at` if the
  agreement says the piece comes down.
- Cancelling is `cancel_schedule` → `approved`. The worker is the only publisher after that,
  using `FOR UPDATE SKIP LOCKED`, so two workers cannot both publish it.

## 5. Investigation and legal

A draft names a company. The editor sets `legal_hold`. The story can keep moving
(`in_review`, `copy_editing`, `approved`) so the desk is not blocked, but `schedule` and
`publish` return an error until an editor records clearance (`article.clear_legal`).
Counsel is not a user of the app. The editor is recording that counsel signed off, and
that action is audited.

## 6. Spike

The editor decides the story should not run: the other outlet had it first, or it does
not hold up.

- `kill` with a reason, from any pre-publish state including `scheduled`.
- Status becomes `killed`. It stays searchable by staff. It is not a soft delete.
- If the story was ever published, `kill` is refused. Taking a live story down is
  `unpublish`.

A writer who created a duplicate by mistake uses `delete` on their own never-published
draft. That is housekeeping. An editorial decision to spike is `kill`.

## 7. Published, then a factual error

Readers already saw the piece.

- Do not delete it and do not kill it.
- Small factual fix that does not change the story: editor (or the writer, as a proposal)
  saves a new revision, editor runs `publish_update`. The live page changes. A public
  `correction` note says what was wrong.
- The story was right but incomplete: a `clarification`, or an `update` note
  ("updated at 14:10 with the ministry statement") plus `publish_update`.
- The story should not be up at all (legal letter, a harm risk, a duplicate of our own
  piece): `unpublish` with a `TakedownReason` (`legal`, `major_error`, `duplicate`,
  `safety`, `other`) and a written reason. The URL returns 410 with a short notice.
  Republish is a separate, audited action.

The writer can open their own live story and save revisions. Those revisions stay on
`current_revision_id`. Readers keep seeing `published_revision_id` until an editor
publishes the update. The writer cannot publish it themselves.

## 8. Two languages, one story

Arabic is the default edition.

- Writer files the Arabic localization and it runs the full desk path to `published`.
- The English localization is a separate row on the same article. It can still be
  `draft` or `in_review`. Readers of `/en/` do not see it. Readers of `/ar/` do.
- Each localization has its own slug, schedule, revisions and audit history.
- A slug change after publication inserts a `slug_redirects` row. The old URL returns 301.

## 9. Desk scope

The politics editor's role is granted with `section_id` = politics. They can publish a
politics story and cannot publish a sports story. A managing editor has the same role
with no section, which covers every desk. Copy editors are usually one desk for the
whole paper, so their grant is global; they still cannot publish.

## 10. Someone leaves

Staff sessions last 12 hours and can be revoked immediately (suspend the user, or revoke
the session). There is no second factor in this version. A reader account is a different
login and a different cookie, so a leaked reader session cannot open the dashboard.
