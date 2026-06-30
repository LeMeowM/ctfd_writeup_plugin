import os

# Plugin config keys (read from app.config first, then env, then default).
DEFAULTS = {
    "WRITEUPS_REPO_PATH": "/data/writeups-repo",   # local working copy synced from git
    "WRITEUPS_WEBHOOK_SECRET": "",                  # HMAC secret; empty disables webhook
    "WRITEUPS_OPEN_AFTER_CTF": False,               # post-CTF toggle; default keep gate
    "WRITEUPS_UNCENSORED_BIND_URI": "sqlite:////data/uncensored.db",
}


def get(app, key):
    if key in app.config and app.config[key] not in (None, ""):
        return app.config[key]
    env = os.environ.get(key)
    if env is not None:
        return env
    return DEFAULTS[key]
