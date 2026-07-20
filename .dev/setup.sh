#!/usr/bin/env bash
# One-time (idempotent) setup for the local dev CTFd instance.
#
# Clones CTFd 3.7.6 into .ctfd-src/, creates .venv/ with the right
# dependencies, wires CTFd onto the venv's sys.path, symlinks this repo's
# plugin into CTFd's plugins dir, and seeds the instance (admin/player
# accounts, sample challenges, sample writeups).
#
# Safe to re-run: every step is skipped if already done.
#
# Usage: .dev/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

CTFD_TAG="3.7.6"
CTFD_SRC="$REPO_ROOT/.ctfd-src"
VENV="$REPO_ROOT/.venv"

log() { printf '==> %s\n' "$1"; }

for cmd in git python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "error: '$cmd' is required but not found on PATH" >&2
        exit 1
    fi
done

# 1. Clone CTFd source.
if [ -d "$CTFD_SRC/.git" ]; then
    log "CTFd source already present at .ctfd-src/ (skipping clone)"
else
    log "Cloning CTFd $CTFD_TAG into .ctfd-src/"
    git clone --quiet --branch "$CTFD_TAG" --depth 1 https://github.com/CTFd/CTFd.git "$CTFD_SRC"
fi

# 2. Create the venv.
if [ -x "$VENV/bin/python" ]; then
    log ".venv already exists (skipping creation)"
else
    log "Creating .venv"
    python3 -m venv "$VENV"
fi

# 3. Install dependencies: CTFd's own pinned requirements, then this repo's.
# CTFd 3.7.6 has no setup.py/pyproject.toml, so it can't be `pip install`ed
# as a package — its requirements.txt is installed directly instead, and
# CTFd is put on sys.path via the ctfd.pth file written in step 4.
log "Installing CTFd's dependencies (this can take a minute)"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$CTFD_SRC/requirements.txt"
log "Installing plugin dev dependencies"
"$VENV/bin/pip" install --quiet -r "$REPO_ROOT/requirements-dev.txt"

# 4. Point the venv at .ctfd-src so `import CTFd` resolves there.
SITE_PACKAGES="$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
PTH_FILE="$SITE_PACKAGES/ctfd.pth"
if [ -f "$PTH_FILE" ] && [ "$(cat "$PTH_FILE")" = "$CTFD_SRC" ]; then
    log "ctfd.pth already wired up (skipping)"
else
    log "Writing $PTH_FILE"
    printf '%s\n' "$CTFD_SRC" > "$PTH_FILE"
fi

# 5. Symlink the plugin into CTFd's plugins directory.
PLUGIN_LINK="$CTFD_SRC/CTFd/plugins/ctfd_censored_writeups"
if [ -L "$PLUGIN_LINK" ] || [ -e "$PLUGIN_LINK" ]; then
    log "Plugin already linked into CTFd/plugins/ (skipping)"
else
    log "Symlinking plugin into CTFd/plugins/"
    ln -s "$REPO_ROOT/ctfd_censored_writeups" "$PLUGIN_LINK"
fi

# 6. Seed the instance: setup wizard, admin/player accounts, sample
# challenges, and sync of the sample writeups. seed.py is itself idempotent.
log "Seeding the dev instance"
source "$REPO_ROOT/.dev/env.sh"
"$VENV/bin/python" "$REPO_ROOT/.dev/seed.py"

log "Setup complete. Start the server with: .dev/run.sh"
