# Writeup Submission System — Design

**Date:** 2026-07-19
**Status:** Approved

## Purpose

Let CTF players submit writeups for challenges they solved, from the plugin's
`/writeups` page. Submissions land in a moderation queue; admins review them
(including adding missed censoring), optionally grade them, and approve or
reject. Approved writeups are published into the plugin's existing
`Writeup`/`WriteupUncensored` tables and served exactly like synced writeups.
Discord webhooks announce new submissions and review decisions. A local-LLM
pre-review is designed as a hook but not implemented.

## Decisions (from brainstorming)

- **Submission UI lives in the CTFd plugin's `/writeups` page**, not on
  polygl0ts.github.io (static site, no backend).
- **Only solvers may submit** — a user/team must have solved the challenge.
- **Structured form for frontmatter** (challenge dropdown, title, author) plus
  a markdown body via textarea or `.md` file upload.
- **Grading:** optional integer score + comment, internal (admin-only).
- **LLM pre-review:** schema/UI hook reserved now, implementation later.
- **Feedback loop:** submitters see status (pending/approved/rejected) and the
  admin comment on rejection, and can resubmit.
- **Publishing (Approach A):** approved submissions are written directly to
  the plugin DB under a `submission://<id>` source-key namespace; the file
  sync is taught to leave that namespace alone. Git repo and submissions
  coexist as two sources of writeups.
- **Images:** externally hosted only (imgur, GitHub, etc.), referenced by URL.
  No upload support. Documented for authors; admins check images during
  review because **the redaction engine cannot censor an image**.

## Data model

New table `WriteupSubmission`, **in the uncensored bind**
(`__bind_key__ = "uncensored"`): a raw submission body is presumed to contain
flags, and the main DB must never hold secrets.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | becomes the published `source_key` (`submission://<id>`) |
| `challenge_id` | int, not null | resolved at submit time from the dropdown |
| `user_id` | int, not null | submitting CTFd user |
| `account_id` | int, not null | user or team id per mode; what eligibility was checked against |
| `title` | text, not null | |
| `author` | text, not null | defaults to user's display name, editable |
| `body_raw` | text, not null | markdown as submitted; may contain redaction markers |
| `body_edited` | text, null | admin-edited body; published body is `body_edited or body_raw` |
| `status` | string, not null | `pending` / `approved` / `rejected` |
| `admin_comment` | text, null | required on reject; shown to submitter |
| `score` | int, null | internal grade, admin-only |
| `reviewed_by` | int, null | admin user id |
| `reviewed_at` | datetime, null | |
| `llm_report` | text, null | reserved: JSON `{"verdict", "summary", "suggested_score"}`; nothing writes it yet |
| `writeup_id` | int, null | set on approval; links to published `Writeup` row |
| `created_at`, `updated_at` | datetime | |

Rules baked into the model:

- **One live submission per (user_id, challenge_id).** Resubmission
  overwrites the existing pending/rejected row and resets it to `pending`.
  Approved submissions are frozen for the submitter; revising a published
  writeup is an admin action (re-open).
- **Publishing reuses the existing pipeline.** Approval composes a canonical
  document (server-built YAML frontmatter using the numeric challenge ID +
  final body) and runs it through `parse_writeup_file` → redaction →
  static-flag scan, then upserts `Writeup` + `WriteupUncensored` with
  `source_key = "submission://<id>"`. One redaction engine, one fail-closed
  path.

### Change to existing code

`sync_from_dir`'s deletion pass skips rows whose `source_key` starts with
`submission://`. (The upsert pass can't collide: source keys from sync are
repo-relative file paths and can never start with that prefix.) The
flag-scan logic in `sync.py` is factored into a shared helper so the publish
path uses the identical check.

## Submitter flow

- **Entry points:** a "Submit a writeup" section on the plugin's `/writeups`
  index page and a "My submissions" view. Server-rendered templates in the
  existing plugin style; no new JS framework.
- **Form fields:**
  - Challenge dropdown listing only challenges the current account has solved
    (via `compat.has_solved`). No solves → form replaced by a
    "solve something first" note.
  - Title (required); author (pre-filled with display name, editable).
  - Body: markdown textarea + `.md` file upload input. A chosen file fills
    the textarea client-side so the user can tweak before submitting.
  - Inline reminder of the redaction syntax (`<!--redact-->…<!--/redact-->`,
    ```` ```flag ````/```` ```spoiler ```` fences) linking to
    `docs/writeup-format.md`, plus a note that images must be hosted
    externally (imgur, GitHub, …) and referenced by URL — no base64
    data-URIs.
- **On POST**, validated server-side in order: logged in → challenge exists
  and account solved it → title/body non-empty and body ≤ 1 MB → upsert the
  (user, challenge) row as `pending` → fire the "submitted" Discord webhook
  (best-effort). If the existing row for that (user, challenge) is
  `approved`, the POST is rejected with "already published — contact an
  admin" (the form hides those challenges from the dropdown). The body is stored verbatim; no parsing at submit time —
  a malformed body is the reviewer's to fix or reject.
- **My submissions:** the user's own submissions with status badge, the admin
  comment when rejected, and for pending/rejected an "edit & resubmit" button
  that reopens the pre-filled form. Approved entries link to the published
  writeup.
- **Timing:** submissions are open whenever the user can log in and has a
  solve. No separate open/close config for now.

## Admin review flow

- **Queue:** a section on the existing admin writeups page (same admin-only
  access check), listing submissions filterable by status (default
  `pending`): challenge, title, author, submitter, submitted date, score.
- **Review page** (one submission):
  - Side-by-side: editable raw-markdown textarea | rendered **censored
    preview** produced by the real parser/redaction pipeline — exactly what a
    non-solver would see. A "re-preview" action re-renders after edits.
    The preview renders images (spoiler check: images cannot be redacted, so
    the reviewer must eyeball every image for flag/solution leakage).
  - Admin edits (typically wrapping missed spoilers in redaction markers) are
    saved to `body_edited`; `body_raw` keeps the submitter's original.
  - Pipeline warnings shown inline: parse failure, unclosed markers
    (fail-closed), static flag present in censored output. **Approval is
    blocked while any warning is active** — unlike sync there is a human in
    the loop, so we block rather than quarantine.
  - Decision controls: optional integer score, comment (required on reject,
    optional on approve), Approve / Reject buttons.
- **On approve:** run the shared publish pipeline → upsert
  `Writeup`/`WriteupUncensored` (`visible=True`, `quarantined=False`) → set
  `status=approved`, `writeup_id`, `reviewed_by/at` → fire the "reviewed"
  webhook. The writeup is immediately live, gated by the same solver/
  visibility rules as synced writeups.
- **On reject:** set status/comment/reviewer fields; fire the webhook.
  Nothing is published.
- **Re-review:** an approved submission can be re-opened; this sets it back
  to `pending`, deletes the published `Writeup`/`WriteupUncensored` rows, and
  clears `writeup_id`.

## Discord notifications

- Config: `WRITEUPS_DISCORD_WEBHOOK_URL` via the existing plugin config
  mechanism. Empty/unset = feature off.
- Events:
  - **Submitted** (new submissions *and* resubmissions): "📝 New writeup
    pending review: *{title}* for *{challenge}* by {author}".
  - **Reviewed:** "✅ Approved / ❌ Rejected: *{title}* for *{challenge}*",
    plus the score if given. The admin comment is never included (it may be
    submitter-directed feedback; the channel may be semi-public).
- Delivery is best-effort and non-blocking: fired after the DB commit, short
  timeout (~5 s), failures logged and swallowed. Payloads never contain
  writeup bodies — titles and challenge names only.

## LLM pre-review hook (not implemented)

- Reserved now: the `llm_report` column and a read-only block on the review
  page rendered when `llm_report` is non-null.
- Intended future shape (for the later project): a separate worker/CLI
  command (e.g. `flask writeups llm-review`) scans pending submissions with
  `llm_report IS NULL`, calls a configured local endpoint (Ollama-style),
  and writes back JSON `{"verdict", "summary", "suggested_score"}`.
- Nothing in this project calls an LLM.

## Error handling

- Eligibility failures (not logged in / didn't solve / hidden challenge):
  403 or redirect with flash message.
- Resubmit-vs-review race: decision POSTs carry the submission's
  `updated_at`; if it changed since the review page loaded, reject with
  "submission changed, reload".
- Publish failures block approval with the specific reason inline; the
  submission stays `pending`; the publish runs transactionally (savepoint
  pattern as in `sync_from_dir`) so nothing partial is written.
- Webhook failures: logged, swallowed, never surfaced to the submitter.
- Body size cap (1 MB) enforced server-side with a clear message. (The cap
  does not constrain images: markdown images are URLs; base64 embedding is
  documented as disallowed.)

## Testing

pytest, same harness as the existing suite:

- **Submission:** solver can submit; non-solver gets 403 even with a forged
  challenge ID (IDOR-style, matching the existing pattern); resubmit
  overwrites and resets to pending; submitter cannot overwrite an approved
  submission; size cap enforced.
- **Storage bind:** submission rows live in the uncensored bind; the main-DB
  dump contains no raw bodies.
- **Review/publish:** approval publishes a writeup gated identically to
  synced ones (censored for non-solvers, full for solvers); approval blocked
  when the censored output would contain a static flag or markers are
  unclosed; reject publishes nothing; `body_edited` wins over `body_raw`;
  re-open unpublishes.
- **Sync coexistence:** a full `sync_from_dir` run leaves `submission://`
  rows untouched — the critical regression test for the one change to
  existing code.
- **Webhooks:** fired on submit/review against a mocked endpoint; a raising
  webhook does not fail the request; payloads never contain body text.

## Out of scope

- LLM implementation (hook only).
- Image uploads / attachment storage (external hosting only).
- Public grades or leaderboards for writeups.
- Submission open/close windows.
- Publishing to polygl0ts.github.io.
