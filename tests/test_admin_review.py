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


def _decide(client, app, sid, action, body=None, score="", comment=""):
    from ctfd_censored_writeups.models import WriteupSubmission
    with app.app_context():
        s = app.db.session.get(WriteupSubmission, sid)
        token = s.updated_at.isoformat()
        if body is None:
            body = s.body_edited or s.body_raw
    return client.post(f"/admin/writeups/submissions/{sid}/decide", data={
        "nonce": _nonce(client), "action": action, "body": body,
        "score": score, "comment": comment, "updated_at": token,
    })


def test_approve_publishes_gated_writeup(app, make_admin, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    solver = make_user(name="solver", email="s@x.io")
    other = make_user(name="other", email="o@x.io")
    make_solve(user_id=solver.id, challenge_id=c.id)
    sid = _seed_submission(app, c.id, solver.id,
                           body="how: <!--redact-->FLAG{deep}<!--/redact--> done")
    client = _admin_client(app, make_admin)
    r = _decide(client, app, sid, "approve", score="7")
    assert r.status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, Writeup
        s = app.db.session.get(WriteupSubmission, sid)
        assert s.status == "approved"
        assert s.score == 7
        assert s.reviewed_at is not None
        w = Writeup.query.filter_by(source_key=f"submission://{sid}").one()
        assert s.writeup_id == w.id
        cid, wid = w.challenge_id, w.id
    solver_client = login_as_user(app, name="solver", password="pw")
    assert b"FLAG{deep}" in solver_client.get(f"/writeups/{cid}/{wid}").data
    other_client = login_as_user(app, name="other", password="pw")
    resp = other_client.get(f"/writeups/{cid}/{wid}")
    assert resp.status_code == 200
    assert b"FLAG{deep}" not in resp.data


def test_approve_blocked_on_malformed_redaction(app, make_admin, make_user, make_challenge):
    from ctfd_censored_writeups.publish import WARN_MALFORMED
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, body="bad <!--redact-->unclosed")
    client = _admin_client(app, make_admin)
    r = _decide(client, app, sid, "approve")
    assert r.status_code == 400
    assert WARN_MALFORMED.encode() in r.data
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, Writeup
        assert app.db.session.get(WriteupSubmission, sid).status == "pending"
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is None


def test_approve_blocked_on_flag_leak(app, make_admin, make_user, make_challenge):
    from tests.helpers import gen_flag
    from ctfd_censored_writeups.publish import WARN_FLAG_LEAK
    c = make_challenge()
    u = make_user()
    with app.app_context():
        gen_flag(app.db, challenge_id=c.id, content="CTF{oops}")
    sid = _seed_submission(app, c.id, u.id, body="flag is CTF{oops} in plain sight")
    client = _admin_client(app, make_admin)
    r = _decide(client, app, sid, "approve")
    assert r.status_code == 400
    assert WARN_FLAG_LEAK.encode() in r.data


def test_admin_edited_body_is_saved_and_published(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, body="original spoiler CTF{fake}")
    client = _admin_client(app, make_admin)
    edited = "original spoiler <!--redact-->CTF{fake}<!--/redact-->"
    r = _decide(client, app, sid, "approve", body=edited)
    assert r.status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, Writeup, WriteupUncensored
        s = app.db.session.get(WriteupSubmission, sid)
        assert s.body_edited == edited
        assert s.body_raw == "original spoiler CTF{fake}"  # original preserved
        w = Writeup.query.filter_by(source_key=f"submission://{sid}").one()
        assert "CTF{fake}" not in w.censored_body
        assert "CTF{fake}" in WriteupUncensored.query.filter_by(writeup_id=w.id).one().uncensored_body


def test_reject_requires_comment_and_publishes_nothing(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id)
    client = _admin_client(app, make_admin)
    assert _decide(client, app, sid, "reject", comment="").status_code == 400
    r = _decide(client, app, sid, "reject", comment="too thin")
    assert r.status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, Writeup
        s = app.db.session.get(WriteupSubmission, sid)
        assert s.status == "rejected"
        assert s.admin_comment == "too thin"
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is None


def test_stale_updated_at_409(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id)
    client = _admin_client(app, make_admin)
    r = client.post(f"/admin/writeups/submissions/{sid}/decide", data={
        "nonce": _nonce(client), "action": "reject", "body": "x",
        "comment": "c", "updated_at": "2000-01-01T00:00:00",
    })
    assert r.status_code == 409


def test_decide_on_approved_submission_409(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, status="approved")
    client = _admin_client(app, make_admin)
    assert _decide(client, app, sid, "reject", comment="c").status_code == 409


def test_decision_fires_reviewed_webhook_without_comment_text(app, make_admin, make_user, make_challenge, monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json)

    from ctfd_censored_writeups import notify
    monkeypatch.setattr(notify.requests, "post", fake_post)
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    c = make_challenge(name="Hooked")
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, title="Hooked Title")
    client = _admin_client(app, make_admin)
    r = _decide(client, app, sid, "reject", comment="SECRETCOMMENT for submitter")
    assert r.status_code == 302
    assert len(calls) == 1
    msg = calls[0]["content"]
    assert "Rejected" in msg and "Hooked Title" in msg and "Hooked" in msg
    assert "SECRETCOMMENT" not in msg


def test_reopen_unpublishes_and_resets(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id)
    client = _admin_client(app, make_admin)
    assert _decide(client, app, sid, "approve").status_code == 302
    r = client.post(f"/admin/writeups/submissions/{sid}/reopen",
                    data={"nonce": _nonce(client)})
    assert r.status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, Writeup, WriteupUncensored
        s = app.db.session.get(WriteupSubmission, sid)
        assert s.status == "pending"
        assert s.writeup_id is None
        assert s.reviewed_by is None and s.reviewed_at is None
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is None
        assert WriteupUncensored.query.count() == 0


def test_reopen_only_valid_for_approved(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, status="pending")
    client = _admin_client(app, make_admin)
    r = client.post(f"/admin/writeups/submissions/{sid}/reopen",
                    data={"nonce": _nonce(client)})
    assert r.status_code == 400
