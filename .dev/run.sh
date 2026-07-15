#!/usr/bin/env bash
# Start the local dev CTFd instance with the censored-writeups plugin.
# Usage: .dev/run.sh [port]   (default port 4000)
set -euo pipefail
cd "$(dirname "$0")/.."
source .dev/env.sh
exec .venv/bin/python .ctfd-src/serve.py --port "${1:-4000}"
