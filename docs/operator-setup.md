# Operator Setup

This guide covers installing and configuring the CTFd censored-writeups plugin for a CTFd 3.7.6 deployment.

## Prerequisites

- CTFd 3.7.6 (the plugin targets this version; other versions are not tested).
- Python 3.11+.
- A local directory containing writeup Markdown files, optionally a git checkout.

## Installing the Plugin

CTFd loads plugins from the `CTFd/plugins/` directory at startup. Copy (or symlink) the `ctfd_censored_writeups` package folder into that directory:

```bash
cp -r ctfd_censored_writeups /path/to/CTFd/CTFd/plugins/
```

After placing the plugin, restart CTFd. On first boot the plugin calls `app.db.create_all()` which creates the `plugin_writeups` table in the main DB and the `plugin_writeups_uncensored` table in the uncensored bind database.

### Development / test setup

CTFd 3.7.6 is not available on PyPI as a wheel. This repository's development environment keeps a CTFd source clone at `.ctfd-src/` (added to `sys.path` by `pytest.ini`). To run the test suite:

```bash
# Clone CTFd alongside this repo (one-time setup):
git clone https://github.com/CTFd/CTFd .ctfd-src
cd .ctfd-src && git checkout 3.7.6 && cd ..

python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

For a real CTFd deployment, install CTFd normally and drop the plugin folder into `CTFd/plugins/` as described above.

## Configuration

The plugin reads configuration from, in order of priority:

1. `app.config` (CTFd's `config.py` / environment-injected Flask config)
2. Environment variables
3. Built-in defaults

Set any of the following keys:

### `WRITEUPS_REPO_PATH`

**Default**: `/data/writeups-repo`

Absolute path to the local directory containing writeup Markdown files. This should be a git working copy so that the webhook sync can call `git pull` before re-scanning.

```bash
WRITEUPS_REPO_PATH=/srv/ctf/writeups-repo
```

### `WRITEUPS_UNCENSORED_BIND_URI`

**Default**: `sqlite:////data/uncensored.db`

SQLAlchemy connection URI for the uncensored database bind. This is a **separate database** from CTFd's main DB and must remain inaccessible to the web process in a normal request (the web process only opens it when serving a solved-state request).

**Why a separate file/credentials**: the uncensored bind should be stored on a separate volume (or use separate DB credentials) from the main CTFd database. This means exfiltrating the main DB — via SQL injection, a backup leak, or an ORM misconfiguration — yields only the censored writeup bodies. An attacker must compromise both databases independently.

Example values:

```bash
# SQLite (file-based separation)
WRITEUPS_UNCENSORED_BIND_URI=sqlite:////data/uncensored_writeups.db

# PostgreSQL with separate credentials
WRITEUPS_UNCENSORED_BIND_URI=postgresql://wu_uncensored:strongpassword@db-host/uncensored_writeups
```

### `WRITEUPS_WEBHOOK_SECRET`

**Default**: `""` (empty — webhook disabled)

HMAC secret for verifying webhook requests from the git host. If empty, `POST /writeups/_webhook` returns HTTP 503.

**Generating a secret**:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Wiring the git provider**: configure your GitHub / Gitea / GitLab repository's webhook:

- **Payload URL**: `https://<your-ctfd-host>/writeups/_webhook`
- **Content type**: `application/json`
- **Secret**: the value generated above
- **Events**: push events only

The plugin expects the header `X-Hub-Signature-256: sha256=<HMAC-SHA256 of raw body>`, which is the default format used by GitHub and Gitea.

```bash
WRITEUPS_WEBHOOK_SECRET=<generated-secret>
```

### `WRITEUPS_OPEN_AFTER_CTF`

**Default**: `False`

When set to `True` (or `"1"`, `"true"`, `"yes"`, `"on"`), all authenticated users receive uncensored writeups once the CTF end time has passed. The gate is still enforced during the CTF. This toggle does not affect the admin preview bypass.

```bash
WRITEUPS_OPEN_AFTER_CTF=true
```

## Initial Seed

After deploying the plugin and placing writeup files in `WRITEUPS_REPO_PATH`, run the initial sync:

```bash
flask writeups sync
```

This command (implemented in `cli.py`):

1. Calls `git pull` if `WRITEUPS_REPO_PATH` is a git repository (`.git/` present).
2. Walks all `*.md` files and upserts them into the database.
3. Prints a summary: `created=N updated=N deleted=N quarantined=N errors=N`.

Inspect the `quarantined` count — any non-zero value means some files failed to parse or resolve; check the `errors` list in the output.

Subsequent syncs can be triggered via the admin "Sync now" button at `/admin/writeups` or via the webhook.

## Admin Page

Navigate to `/admin/writeups` while logged in as an admin. The page shows:

- Total writeup count and quarantined count.
- A "Sync now" button that triggers `POST /admin/writeups/sync`.

See [operator-setup.md](operator-setup.md) (this file) and [writeup-format.md](../ctfd_censored_writeups/docs/writeup-format.md) for the full format reference.
