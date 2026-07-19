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


def test_review_page_renders_censored_preview_and_warnings(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, body="pre <!--redact-->FLAG{x}<!--/redact--> post")
    client = _admin_client(app, make_admin)
    r = client.get(f"/admin/writeups/submissions/{sid}")
    assert r.status_code == 200
    assert b"FLAG{x}" in r.data          # raw body shown in the edit textarea
    assert "〔redacted".encode() in r.data  # censored preview rendered
    assert b"Approve" in r.data and b"Reject" in r.data


def test_review_page_shows_malformed_warning(app, make_admin, make_user, make_challenge):
    from ctfd_censored_writeups.publish import WARN_MALFORMED
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, body="broken <!--redact-->no close")
    client = _admin_client(app, make_admin)
    r = client.get(f"/admin/writeups/submissions/{sid}")
    assert WARN_MALFORMED.encode() in r.data


def test_review_page_shows_llm_report_when_present(app, make_admin, make_user, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id)
    with app.app_context():
        s = app.db.session.get(WriteupSubmission, sid)
        s.llm_report = '{"verdict": "looks-good", "summary": "solid writeup"}'
        app.db.session.commit()
    client = _admin_client(app, make_admin)
    r = client.get(f"/admin/writeups/submissions/{sid}")
    assert b"looks-good" in r.data


def test_review_page_404_on_unknown(app, make_admin):
    client = _admin_client(app, make_admin)
    assert client.get("/admin/writeups/submissions/99999").status_code == 404


def test_preview_endpoint_renders_posted_body(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id)
    client = _admin_client(app, make_admin)
    r = client.post(f"/admin/writeups/submissions/{sid}/preview",
                    data={"nonce": _nonce(client),
                          "body": "now with <!--redact-->FLAG{y}<!--/redact--> marker"},
                    )
    assert r.status_code == 200
    j = r.get_json()
    assert j["success"] is True
    assert "FLAG{y}" not in j["html"]
    assert "redacted" in j["html"]
    assert j["warnings"] == []


def test_preview_endpoint_reports_warnings_and_persists_nothing(app, make_admin, make_user, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission
    from ctfd_censored_writeups.publish import WARN_MALFORMED
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, body="original body")
    client = _admin_client(app, make_admin)
    r = client.post(f"/admin/writeups/submissions/{sid}/preview",
                    data={"nonce": _nonce(client), "body": "bad <!--redact-->"})
    assert WARN_MALFORMED in r.get_json()["warnings"]
    with app.app_context():
        s = app.db.session.get(WriteupSubmission, sid)
        assert s.body_raw == "original body"
        assert s.body_edited is None
