#!/usr/bin/env bash
# Start the local dev CTFd instance with the censored-writeups plugin.
# Runs .dev/setup.sh automatically on first use (or after .venv/.ctfd-src
# have been removed) so this works out of the box on a fresh clone.
# Usage: .dev/run.sh [port]   (default port 4000)
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ] || [ ! -d .ctfd-src ]; then
    .dev/setup.sh
fi
source .dev/env.sh
exec .venv/bin/python .ctfd-src/serve.py --port "${1:-4000}"
