# Dev environment for the local CTFd test instance. Source from the repo root.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
export WRITEUPS_REPO_PATH="$REPO_ROOT/.dev/writeups-repo"
export WRITEUPS_UNCENSORED_BIND_URI="sqlite:///$REPO_ROOT/.dev/uncensored.db"
export WRITEUPS_WEBHOOK_SECRET="dev-webhook-secret-only-for-local-testing"
