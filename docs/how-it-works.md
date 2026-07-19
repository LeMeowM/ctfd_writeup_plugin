# How It Works

This document describes the internal architecture of the CTFd censored-writeups plugin.

## Core Invariant

A user who has not solved a challenge never receives the uncensored writeup body. All leakage paths are closed at the storage layer, not only at the view layer.

## The Solve Gate

The gate decision is made by `gate.decide(app, user, challenge_id)` in `gate.py`. It returns one of two constants: `"censored"` or `"uncensored"`.

Decision tree (in order):

1. **Unauthenticated** (`user is None`) → censored.
2. **Admin** (`user.type == "admin"`) → uncensored (preview bypass).
3. **Post-CTF toggle**: if the CTF has ended (per `CTFd.utils.dates.ctf_ended`) **and** `WRITEUPS_OPEN_AFTER_CTF` is `True` → uncensored for all authenticated users.
4. **Team mode**: the account identifier used for the solve lookup is the user's `team_id`. A user who is not a member of any team has `team_id = None`, which is treated as unsolved → censored.
5. **User mode**: the account identifier is `user.account_id`.
6. The solve table is queried (`Solves`). If the account has a solve record for the challenge → uncensored, otherwise → censored.

**Team mode detail**: in team mode, any teammate's solve unlocks the writeup for the whole team, because the solve is recorded under the team's ID. Individual users without a team are never granted uncensored access regardless of their own solve history.

**Post-CTF toggle default**: `WRITEUPS_OPEN_AFTER_CTF` defaults to `False`, meaning the gate remains active after the CTF ends unless the operator explicitly enables the toggle.

## Two-Bind Storage Model

The plugin stores writeup content across two independent SQLAlchemy databases:

| Model | Bind key | Table | Content |
|---|---|---|---|
| `Writeup` | (default, main CTFd DB) | `plugin_writeups` | Metadata + **censored** body |
| `WriteupUncensored` | `uncensored` | `plugin_writeups_uncensored` | **Uncensored** body |

The `uncensored` bind is a separate database file (or credentials) configured via `WRITEUPS_UNCENSORED_BIND_URI`. There is no cross-bind foreign key by design; the join is done in Python via `writeup_id`.

**Defense-in-depth this buys**: the unsolved request path (`gate.decide` returns `"censored"`) never opens the `WriteupUncensored` model. A SQL injection or ORM misconfiguration on the censored path cannot reach the uncensored table because it lives in a completely separate database connection. Even if the main DB is exfiltrated, it contains only the censored body.

The `_render_body` function in `views.py` enforces this:

- If `decision == UNCENSORED`: queries `WriteupUncensored` and returns `unlocked=True`.
- Otherwise: uses `writeup.censored_body` directly, never touching the uncensored bind.

## Sync Flow

Content flows from a local directory (a git checkout) into the DB via the sync engine (`sync.py`).

### Triggers

Three ways to trigger a sync:

1. **Webhook**: `POST /writeups/_webhook` — HMAC-verified (see below). The git host calls this on push; the plugin pulls and syncs.
2. **Admin button**: `POST /admin/writeups/sync` — the "Sync now" button on the admin page triggers a pull + sync.
3. **CLI**: `flask writeups sync` — runs `git pull` (if the path is a git repo) then syncs.

### Webhook authentication

The webhook endpoint requires the `WRITEUPS_WEBHOOK_SECRET` config key to be set (a non-empty value). Requests without it return HTTP 503.

The expected header is:

```
X-Hub-Signature-256: sha256=<HMAC-SHA256 of the raw request body using the secret>
```

This is the same format used by GitHub and Gitea. The comparison uses `hmac.compare_digest` to prevent timing attacks.

### Sync algorithm (`sync_from_dir`)

1. Walk all `*.md` files under `WRITEUPS_REPO_PATH` recursively.
2. For each file, open a **savepoint** (nested transaction). A crash or parse error in one file rolls back only that file's work; the rest of the sync continues.
3. Parse the file (`parser.parse_writeup_file`): extract frontmatter, apply redaction, compute censored body.
4. Resolve the challenge (`compat.resolve_challenge_id`): map the `challenge` field to a DB challenge ID.
5. **Flag scan**: if the challenge resolved and the writeup is otherwise ok, fetch all static flags for the challenge and check whether any flag value appears as a literal substring in the censored body. A match quarantines the writeup and records an error. (Dynamic/regex flags are not scanned — see Limitations.)
6. Determine `quarantined`: `True` if any of: parse failed (`parsed.ok == False`), challenge unresolved (`challenge_id is None`), or flag leaked into censored body.
7. **Upsert** into `Writeup` (keyed by `source_key`): write metadata and censored body.
8. **Upsert** into `WriteupUncensored` (keyed by `writeup_id`): write uncensored body.
9. Commit the savepoint.
10. After the walk, **deletion pass**: any `Writeup` rows whose `source_key` is not in the current file set are deleted from both binds.

The sync is **idempotent**: a second identical run with no file changes reports `created=0, updated=0, deleted=0`.

### Quarantine behavior

A quarantined writeup (`quarantined=True`) is:
- Stored in the DB (so errors are visible to operators via the admin page count).
- Never returned by any route (`/writeups/...`, `/api/v1/writeups/...`): routes filter `quarantined=False`.
- Never rendered to users.

Quarantine triggers:
- Missing or invalid YAML frontmatter.
- Empty or unresolvable `challenge` field (challenge does not exist, name matches zero or two-or-more challenges).
- Redaction engine returned `ok=False` (unclosed/nested markers, unclosed fence, or verification failure).
- A static flag value found verbatim in the censored body.

## API Shapes

All routes require authentication (`@authed_only`). All responses carry `Cache-Control: private, no-store`.

### List writeups for a challenge

`GET /api/v1/writeups/<challenge_id>`

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "challenge_id": 5,
      "title": "My Approach",
      "author": "alice",
      "tags": ["web", "ssti"],
      "sort_order": 0,
      "unlocked": true
    }
  ]
}
```

### Single writeup (rendered)

`GET /api/v1/writeups/<challenge_id>/<writeup_id>`

```json
{
  "success": true,
  "data": {
    "id": 1,
    "title": "My Approach",
    "unlocked": true,
    "body": "<p>Rendered HTML…</p>"
  }
}
```

`unlocked: false` means the body contains the censored version with placeholder strings. The body is always rendered HTML (via CTFd's `markdown()` helper).

**IDOR discipline**: the `challenge_id` in the URL is **not used** to look up the writeup. The writeup is fetched by `writeup_id` alone. The gate decision uses the `challenge_id` stored in the DB row, not the URL parameter. This prevents an attacker from supplying a solved challenge's ID to unlock a different challenge's writeup.

## HTML Routes

- `GET /writeups` — index listing all challenges with at least one visible, non-quarantined writeup. Currently shows "Challenge #N" links (no challenge name join — see Limitations).
- `GET /writeups/<challenge_id>` — list writeups for a challenge (HTML template).
- `GET /writeups/<challenge_id>/<writeup_id>` — single writeup page (HTML template).

## Challenge Modal Tab

The plugin adds a "Writeups" tab to the challenge modal on the challenges page, next to the built-in "Challenge" and "N Solves" tabs.

**Mechanism**: `challenge-tab.js` is registered via CTFd's `register_plugin_script()`, so it loads on every page (no theme template is overridden). On the challenges page, the core-beta theme re-renders the modal's inner HTML into `#challenge-window` each time a challenge is opened; the script observes that container with a `MutationObserver` and injects, per render, a Bootstrap tab button (`data-bs-toggle="tab"`) and a pane (`#writeups`).

**Content**: the pane fetches `GET /api/v1/writeups/<challenge_id>` and lists each visible writeup as a link to its `/writeups/<challenge_id>/<writeup_id>` page (opened in a new browser tab), with the author and a lock icon on entries the viewer has not unlocked. The tab label becomes "Writeups (N)". With zero writeups — or if the API call fails — the pane reads "No writeups yet". Titles and authors are rendered with `textContent`, so writeup metadata cannot inject HTML.

**Theme dependency (fail-silent)**: the injection requires the core-beta modal markup (`#challenge-window`, `.nav-tabs`, `.tab-content`, `#challenge-id`). On a theme where any of these is absent, the script does nothing and the modal renders exactly as stock. The solve gate is unaffected either way: the tab only shows metadata the list API already exposes, and the linked pages enforce censoring server-side.

## Player Submissions

Submissions live in `plugin_writeup_submissions` **in the uncensored bind** —
an unreviewed body is presumed to contain flags, so it never touches the main
DB. One live submission per (user, challenge); resubmitting a pending or
rejected writeup overwrites it and resets review state.

On approval, the plugin composes a frontmatter document (numeric challenge
ID, title, author + the admin-final body) and runs it through the same
`parse_writeup_file` → redaction → static-flag-scan pipeline as file sync,
then upserts `Writeup`/`WriteupUncensored` with `source_key =
"submission://<id>"`. Approval is **blocked** (not quarantined) while the
body fails to parse or leaks a static flag — there is a human in the loop to
fix it. `sync_from_dir`'s deletion pass skips the `submission://` namespace,
so file sync and submissions coexist.

The admin review page shows the raw body in an editor next to a rendered
censored preview (the real pipeline output). Admin edits are stored in
`body_edited`; the submitter's original stays in `body_raw`. An approved
submission can be re-opened, which unpublishes it and returns it to the
queue. The `llm_report` column is reserved for a future local-LLM pre-review
worker (e.g. `flask writeups llm-review` scanning pending submissions and
writing back `{"verdict", "summary", "suggested_score"}`); nothing writes it
today.

## Known Limitations

- **`/writeups` index shows "Challenge #N"**: the index template lists challenge IDs without joining the `Challenges` table to show names. A future improvement would add a name-resolution step.
- **Dynamic/regex flags not scanned**: the flag scan in sync only checks static flag strings (`Flags.type == "static"`). If a challenge uses a dynamic or regex flag, the scan is silently skipped for that challenge. Authors must ensure no flag-like content appears in the censored body of such challenges.
- **Admin page is self-contained**: the `/admin/writeups` page is a minimal standalone HTML page; it does not inherit the CTFd admin navigation chrome.
- **Team mode is fully supported**: team-mode solve gating is implemented and tested end-to-end.
