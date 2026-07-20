"""
Stored XSS regression tests: submitted markdown bodies must be sanitized
before they reach any `| safe` / innerHTML render sink. CTFd's markdown()
renders with CMARK_OPT_UNSAFE, so raw HTML (including <script> and
event-handler attributes) passes straight through unless the plugin
sanitizes it itself.
"""


def _nonce(client):
    with client.session_transaction() as sess:
        return sess.get("nonce")


def test_approved_submission_body_is_sanitized_when_served(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    evil = "hello <img src=x onerror=alert(1)> world <script>alert(2)</script>"
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission
        from ctfd_censored_writeups import publish
        sub = WriteupSubmission(
            user_id=u.id, challenge_id=c.id, account_id=u.id,
            title="Evil", author=u.name, body_raw=evil, status="pending",
        )
        app.db.session.add(sub)
        app.db.session.flush()
        w = publish.publish_submission(sub)
        sub.writeup_id = w.id
        sub.status = "approved"
        app.db.session.commit()
        challenge_id, writeup_id = c.id, w.id

    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{challenge_id}/{writeup_id}")
    assert r.status_code == 200
    assert b"onerror" not in r.data
    assert b"<script>" not in r.data
    assert b"hello" in r.data
    assert b"world" in r.data


def test_preview_endpoint_sanitizes_script(app, make_admin, make_user, make_challenge):
    from tests.helpers import login_as_user
    from ctfd_censored_writeups.models import WriteupSubmission
    c = make_challenge()
    u = make_user()
    with app.app_context():
        sub = WriteupSubmission(
            user_id=u.id, challenge_id=c.id, account_id=u.id,
            title="T", author=u.name, body_raw="original", status="pending",
        )
        app.db.session.add(sub)
        app.db.session.commit()
        sid = sub.id

    make_admin()
    client = login_as_user(app, name="testadmin", password="pw")
    r = client.post(
        f"/admin/writeups/submissions/{sid}/preview",
        data={"nonce": _nonce(client), "body": "bad <script>alert(1)</script> ok"},
    )
    assert r.status_code == 200
    j = r.get_json()
    assert "ok" in j["html"]
    assert "<script>" not in j["html"]


def test_normal_markdown_still_renders(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission
        from ctfd_censored_writeups import publish
        sub = WriteupSubmission(
            user_id=u.id, challenge_id=c.id, account_id=u.id,
            title="Bold", author=u.name, body_raw="**bold**", status="pending",
        )
        app.db.session.add(sub)
        app.db.session.flush()
        w = publish.publish_submission(sub)
        sub.writeup_id = w.id
        sub.status = "approved"
        app.db.session.commit()
        challenge_id, writeup_id = c.id, w.id

    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{challenge_id}/{writeup_id}")
    assert r.status_code == 200
    assert b"<strong>" in r.data
