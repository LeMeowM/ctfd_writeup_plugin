# CTFd Censored Writeups Plugin

A CTFd 3.7.6 plugin that publishes writeups for solved challenges only. Users who have not yet solved a challenge see a censored version with spoilers and flags replaced by placeholders. Solving the challenge unlocks the full writeup.

## Core Invariant

> A user who has not solved a challenge never receives the uncensored writeup body.

This is enforced at the storage layer: the censored and uncensored bodies live in two separate databases (two SQLAlchemy binds). The unsolved request path never opens the uncensored bind, so a bug or exfiltration of the main database yields only censored content.

## What It Does

- **Writeup source**: Markdown files in a local directory (typically a git checkout). Each file has a YAML frontmatter block specifying which challenge it belongs to, a title, author, and display options.
- **Redaction**: Authors mark secrets inline with `<!--redact-->…<!--/redact-->` or in fenced `` ```flag `` / `` ```spoiler `` blocks. The plugin strips these on ingest and stores both a censored and an uncensored version.
- **Solve gate**: `gate.decide(app, user, challenge_id)` returns `"censored"` or `"uncensored"`. Admins always get uncensored (preview). In team mode, any teammate's solve unlocks for the whole team.
- **Challenge modal tab**: a "Writeups" tab appears in the challenge modal (core-beta theme), listing each writeup with a lock icon until solved. Injected client-side; silently absent on other themes.
- **Sync**: Push a commit to the writeups repo → git host fires `POST /writeups/_webhook` (HMAC-verified) → plugin pulls and re-syncs. Manual sync also available via the admin page or `flask writeups sync`.
- **Quarantine**: Files that fail to parse, reference an unknown challenge, or contain a flag in their censored body are stored but never served.
- **Player submissions**: solvers can submit writeups from `/writeups/submit` (structured form + markdown body, `.md` upload supported). Admins review at `/admin/writeups`: side-by-side editor with live censored preview, optional internal score, approve/reject with comment. Approved writeups publish instantly under a `submission://<id>` source key that file sync never touches. Optional Discord webhook announces submissions and decisions (`WRITEUPS_DISCORD_WEBHOOK_URL`).

## Documentation

- [Writeup file format](ctfd_censored_writeups/docs/writeup-format.md) — frontmatter fields, redaction markers, fail-closed rules, complete example.
- [How it works](docs/how-it-works.md) — solve gate, two-bind storage model, sync flow, API shapes, known limitations.
- [Operator setup](docs/operator-setup.md) — installation, config keys, webhook wiring, initial seed.
- [Design spec](docs/superpowers/specs/2026-06-30-ctfd-censored-writeups-design.md) — original architecture spec.

## Quick Start

```bash
# 1. Copy plugin into CTFd
cp -r ctfd_censored_writeups /path/to/CTFd/CTFd/plugins/

# 2. Configure (environment variables or app.config)
export WRITEUPS_REPO_PATH=/srv/ctf/writeups-repo
export WRITEUPS_UNCENSORED_BIND_URI=sqlite:////data/uncensored.db
export WRITEUPS_WEBHOOK_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# 3. Restart CTFd, then seed
flask writeups sync
```
