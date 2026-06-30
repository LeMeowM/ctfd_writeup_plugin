import hashlib
import hmac
import os


def _sig(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_rejects_bad_signature(app, tmp_path):
    os.environ["WRITEUPS_WEBHOOK_SECRET"] = "s3cret"
    client = app.test_client()
    r = client.post(
        "/writeups/_webhook",
        data=b"{}",
        headers={"X-Hub-Signature-256": "sha256=bad"},
    )
    assert r.status_code == 401


def test_webhook_accepts_good_signature(app, make_challenge, tmp_path):
    secret = "s3cret"
    os.environ["WRITEUPS_WEBHOOK_SECRET"] = secret
    chal = make_challenge()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.md").write_text(
        f"---\nchallenge: {chal.id}\ntitle: T\n---\nbody"
    )
    os.environ["WRITEUPS_REPO_PATH"] = str(repo)
    body = b"{}"
    client = app.test_client()
    r = client.post(
        "/writeups/_webhook",
        data=body,
        headers={"X-Hub-Signature-256": _sig(secret, body)},
    )
    assert r.status_code == 200
    from ctfd_censored_writeups.models import Writeup

    with app.app_context():
        assert Writeup.query.count() == 1


def test_admin_page_requires_admin(app, make_user):
    from tests.helpers import login_as_user

    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/admin/writeups")
    assert r.status_code in (302, 403)  # non-admin redirected/forbidden


def test_webhook_503_when_secret_unset(app):
    os.environ.pop("WRITEUPS_WEBHOOK_SECRET", None)
    client = app.test_client()
    r = client.post(
        "/writeups/_webhook",
        data=b"{}",
        headers={"X-Hub-Signature-256": "sha256=whatever"},
    )
    assert r.status_code == 503


def test_admin_sync_requires_admin(app, make_user):
    from tests.helpers import login_as_user

    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = client.post("/admin/writeups/sync")
    assert r.status_code in (302, 403)
