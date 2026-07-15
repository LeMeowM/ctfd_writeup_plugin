"""Seed the local dev CTFd instance: setup, users, challenges, flags, writeup sync.

Idempotent — safe to re-run. Run from the repo root:

    source .dev/env.sh && .venv/bin/python .dev/seed.py
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO_ROOT)  # so CTFd finds .ctfd_secret_key at the repo root

os.environ.setdefault("WRITEUPS_REPO_PATH", os.path.join(REPO_ROOT, ".dev", "writeups-repo"))
os.environ.setdefault("WRITEUPS_UNCENSORED_BIND_URI", "sqlite:///" + os.path.join(REPO_ROOT, ".dev", "uncensored.db"))
os.environ.setdefault("WRITEUPS_WEBHOOK_SECRET", "dev-webhook-secret-only-for-local-testing")

from CTFd import create_app  # noqa: E402

app = create_app()

CHALLENGES = [
    # (name, category, description, value, flag)
    ("Web 101", "web", "A beginner web challenge with an SSTI vulnerability.", 100, "CTF{ssti_is_fun}"),
    ("Heap Feng Shui", "pwn", "A heap exploitation challenge with a UAF.", 300, "CTF{heap_master_2026}"),
    ("Crypto Warmup", "crypto", "No writeup exists for this one (tests the empty state).", 50, "CTF{rot13_twice}"),
]


def do_setup():
    from CTFd.utils import get_config
    with app.app_context():
        if get_config("setup"):
            print("setup: already done")
            return
    with app.test_client() as client:
        client.get("/setup")
        with client.session_transaction() as sess:
            nonce = sess.get("nonce")
        r = client.post("/setup", data={
            "ctf_name": "Writeups Dev CTF",
            "ctf_description": "Local instance for testing the censored-writeups plugin",
            "name": "admin",
            "email": "admin@example.com",
            "password": "password",
            "user_mode": "users",
            "ctf_theme": "core-beta",
            "nonce": nonce,
        })
        assert r.status_code in (200, 302), r.status_code
    print("setup: done (admin / password)")


def make_player():
    from CTFd.models import Users, db
    with app.app_context():
        if Users.query.filter_by(name="player").first():
            print("user: player already exists")
            return
        with app.test_client() as client:
            client.get("/register")
            with client.session_transaction() as sess:
                nonce = sess.get("nonce")
            r = client.post("/register", data={
                "name": "player",
                "email": "player@example.com",
                "password": "password",
                "nonce": nonce,
            })
            assert r.status_code in (200, 302), r.status_code
        assert Users.query.filter_by(name="player").first() is not None, "player registration failed"
    print("user: player created (player / password)")


def make_challenges():
    from CTFd.models import Challenges, Flags, db
    with app.app_context():
        for name, category, description, value, flag in CHALLENGES:
            if Challenges.query.filter_by(name=name).first():
                print(f"challenge: {name!r} already exists")
                continue
            chal = Challenges(name=name, category=category, description=description,
                              value=value, state="visible", type="standard")
            db.session.add(chal)
            db.session.commit()
            db.session.add(Flags(challenge_id=chal.id, type="static", content=flag))
            db.session.commit()
            print(f"challenge: created {name!r} (flag: {flag})")


def sync_writeups():
    from CTFd.plugins.ctfd_censored_writeups.sync import sync_from_dir
    with app.app_context():
        report = sync_from_dir(app, os.environ["WRITEUPS_REPO_PATH"])
    print(f"sync: {report}")


if __name__ == "__main__":
    do_setup()
    make_player()
    make_challenges()
    sync_writeups()
    print("\nSeeded. Start the server with: .dev/run.sh")
