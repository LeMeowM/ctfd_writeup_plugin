def _nonce(client):
    with client.session_transaction() as sess:
        return sess.get("nonce")


def _seed_submission(app, challenge_id, user_id, title="Queue Title",
                     body="b <!--redact-->FLAG{x}<!--/redact--> a", status="pending"):
    from ctfd_censored_writeups.models import WriteupSubmission
    with app.app_context():
        s = WriteupSubmission(challenge_id=challenge_id, user_id=user_id,
                              account_id=user_id, title=title, author="alice",
                              body_raw=body, status=status)
        app.db.session.add(s)
        app.db.session.commit()
        return s.id


def _admin_client(app, make_admin):
    from tests.helpers import login_as_user
    make_admin()
    return login_as_user(app, name="testadmin", password="pw")


def test_queue_defaults_to_pending(app, make_admin, make_user, make_challenge):
    c = make_challenge(name="Queue Chal")
    u = make_user()
    _seed_submission(app, c.id, u.id, title="PendingOne", status="pending")
    _seed_submission_id2 = _seed_submission(app, c.id, u.id + 1000, title="DoneOne", status="approved")
    client = _admin_client(app, make_admin)
    r = client.get("/admin/writeups")
    assert r.status_code == 200
    assert b"PendingOne" in r.data
    assert b"Queue Chal" in r.data
    assert b"DoneOne" not in r.data


def test_queue_status_filters(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    _seed_submission(app, c.id, u.id, title="PendingOne", status="pending")
    _seed_submission(app, c.id, u.id + 1000, title="ApprovedOne", status="approved")
    client = _admin_client(app, make_admin)
    r = client.get("/admin/writeups?status=approved")
    assert b"ApprovedOne" in r.data and b"PendingOne" not in r.data
    r = client.get("/admin/writeups?status=all")
    assert b"ApprovedOne" in r.data and b"PendingOne" in r.data


def test_queue_requires_admin(app, make_user, make_challenge):
    from tests.helpers import login_as_user
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/admin/writeups", follow_redirects=False)
    assert r.status_code in (302, 403)  # CTFd admins_only redirects non-admins
