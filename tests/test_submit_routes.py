def _nonce(client):
    with client.session_transaction() as sess:
        return sess.get("nonce")


def _submit(client, challenge_id, title="T", body="hello world", author=""):
    return client.post("/writeups/submit", data={
        "nonce": _nonce(client), "challenge_id": challenge_id,
        "title": title, "author": author, "body": body,
    })


def test_form_lists_only_solved_challenges(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    solved = make_challenge(name="Solved One")
    unsolved = make_challenge(name="Not Solved")
    u = make_user()
    make_solve(user_id=u.id, challenge_id=solved.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/writeups/submit")
    assert r.status_code == 200
    assert b"Solved One" in r.data
    assert b"Not Solved" not in r.data


def test_form_without_solves_shows_note(app, make_user, make_challenge):
    from tests.helpers import login_as_user
    make_challenge()
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/writeups/submit")
    assert r.status_code == 200
    assert b"solve" in r.data.lower()


def test_solver_can_submit(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = _submit(client, c.id, body="I solved it like this")
    assert r.status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission
        s = WriteupSubmission.query.one()
        assert s.challenge_id == c.id
        assert s.user_id == u.id
        assert s.status == "pending"
        assert s.author == u.name  # empty author falls back to display name
        assert s.body_raw == "I solved it like this"


def test_non_solver_gets_403_even_with_forged_id(app, make_user, make_challenge):
    """IDOR discipline: the dropdown only shows solved challenges, but the POST
    must re-check server-side."""
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = _submit(client, c.id)
    assert r.status_code == 403
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission
        assert WriteupSubmission.query.count() == 0


def test_unknown_challenge_404(app, make_user):
    from tests.helpers import login_as_user
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, 99999).status_code == 404


def test_hidden_challenge_403(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge(state="hidden")
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id).status_code == 403


def test_empty_title_or_body_400(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id, title="  ").status_code == 400
    assert _submit(client, c.id, body="  ").status_code == 400


def test_body_size_cap_413(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id, body="x" * (1_048_576 + 1)).status_code == 413


def test_resubmit_overwrites_and_resets(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id, title="v1", body="first").status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, STATUS_REJECTED
        s = WriteupSubmission.query.one()
        s.status = STATUS_REJECTED
        s.admin_comment = "too short"
        s.score = 2
        s.body_edited = "admin tweak"
        s.llm_report = '{"verdict": "stale"}'
        app.db.session.commit()
    assert _submit(client, c.id, title="v2", body="second, longer").status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission
        s = WriteupSubmission.query.one()  # still exactly one row
        assert s.title == "v2"
        assert s.body_raw == "second, longer"
        assert s.status == "pending"
        assert s.admin_comment is None
        assert s.score is None
        assert s.body_edited is None
        assert s.llm_report is None


def test_cannot_overwrite_approved_submission(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id).status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, STATUS_APPROVED
        s = WriteupSubmission.query.one()
        s.status = STATUS_APPROVED
        app.db.session.commit()
    assert _submit(client, c.id, title="try again").status_code == 409


def test_submit_fires_webhook_without_body_text(app, make_user, make_challenge, make_solve, monkeypatch):
    from tests.helpers import login_as_user
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json)

    from ctfd_censored_writeups import notify
    monkeypatch.setattr(notify.requests, "post", fake_post)
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    c = make_challenge(name="Webby")
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = _submit(client, c.id, title="Hook Title", body="SECRETBODY FLAG{x}")
    assert r.status_code == 302
    assert len(calls) == 1
    msg = calls[0]["content"]
    assert "Hook Title" in msg and "Webby" in msg
    assert "SECRETBODY" not in msg and "FLAG{x}" not in msg


def test_webhook_failure_does_not_break_submit(app, make_user, make_challenge, make_solve, monkeypatch):
    from tests.helpers import login_as_user

    def boom(url, json=None, timeout=None):
        raise RuntimeError("down")

    from ctfd_censored_writeups import notify
    monkeypatch.setattr(notify.requests, "post", boom)
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id).status_code == 302
