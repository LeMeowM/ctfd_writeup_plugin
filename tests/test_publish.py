def test_compose_document_roundtrips_through_parser(app):
    from ctfd_censored_writeups.publish import compose_document
    from ctfd_censored_writeups.parser import parse_writeup_file
    doc = compose_document(42, "My Title", "alice", "hello <!--redact-->FLAG{x}<!--/redact--> world")
    p = parse_writeup_file(doc, "submission://1")
    assert p.ok
    assert p.challenge_ref == "42"          # numeric -> resolved as ID, never ambiguous
    assert p.title == "My Title"
    assert p.author == "alice"
    assert "FLAG{x}" not in p.censored_body
    assert "FLAG{x}" in p.uncensored_body


def test_compose_document_handles_tricky_yaml_title(app):
    from ctfd_censored_writeups.publish import compose_document
    from ctfd_censored_writeups.parser import parse_writeup_file
    doc = compose_document(7, 'Quote " and : colon', None, "body")
    p = parse_writeup_file(doc, "k")
    assert p.ok
    assert p.title == 'Quote " and : colon'
    assert p.author is None


def test_evaluate_clean_body_has_no_warnings(app, make_challenge):
    from ctfd_censored_writeups.publish import evaluate
    c = make_challenge()
    with app.app_context():
        ev = evaluate(c.id, "safe <!--redact-->FLAG{x}<!--/redact--> text")
        assert ev.warnings == []
        assert "FLAG{x}" not in ev.parsed.censored_body


def test_evaluate_flags_malformed_redaction(app, make_challenge):
    from ctfd_censored_writeups.publish import evaluate, WARN_MALFORMED
    c = make_challenge()
    with app.app_context():
        ev = evaluate(c.id, "oops <!--redact-->never closed")
        assert WARN_MALFORMED in ev.warnings


def test_evaluate_flags_static_flag_leak(app, make_challenge):
    from tests.helpers import gen_flag
    from ctfd_censored_writeups.publish import evaluate, WARN_FLAG_LEAK
    c = make_challenge()
    with app.app_context():
        gen_flag(app.db, challenge_id=c.id, content="CTF{leaky}")
        ev = evaluate(c.id, "the flag is CTF{leaky}, whoops")
        assert WARN_FLAG_LEAK in ev.warnings


def test_source_key_namespace(app):
    from ctfd_censored_writeups.publish import source_key_for, SUBMISSION_PREFIX
    assert source_key_for(9) == "submission://9"
    assert source_key_for(9).startswith(SUBMISSION_PREFIX)


def _make_submission(app, challenge_id, body="b <!--redact-->FLAG{x}<!--/redact--> a",
                     user_id=2, title="T", author="alice"):
    from ctfd_censored_writeups.models import WriteupSubmission
    with app.app_context():
        s = WriteupSubmission(challenge_id=challenge_id, user_id=user_id,
                              account_id=user_id, title=title, author=author,
                              body_raw=body)
        app.db.session.add(s)
        app.db.session.commit()
        sid = s.id
    return sid


def test_publish_submission_upserts_both_binds(app, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission, Writeup, WriteupUncensored
    from ctfd_censored_writeups.publish import publish_submission
    c = make_challenge()
    sid = _make_submission(app, c.id)
    with app.app_context():
        sub = app.db.session.get(WriteupSubmission, sid)
        w = publish_submission(sub)
        app.db.session.commit()
        got = Writeup.query.filter_by(source_key=f"submission://{sid}").one()
        assert got.id == w.id
        assert got.challenge_id == c.id
        assert got.title == "T"
        assert got.author == "alice"
        assert got.visible is True
        assert got.quarantined is False
        assert "FLAG{x}" not in got.censored_body
        u = WriteupUncensored.query.filter_by(writeup_id=got.id).one()
        assert "FLAG{x}" in u.uncensored_body


def test_publish_submission_uses_edited_body_when_present(app, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission, Writeup, WriteupUncensored
    from ctfd_censored_writeups.publish import publish_submission
    c = make_challenge()
    sid = _make_submission(app, c.id, body="original")
    with app.app_context():
        sub = app.db.session.get(WriteupSubmission, sid)
        sub.body_edited = "edited by admin"
        w = publish_submission(sub)
        app.db.session.commit()
        assert "edited by admin" in WriteupUncensored.query.filter_by(writeup_id=w.id).one().uncensored_body


def test_republish_is_idempotent_upsert(app, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission, Writeup
    from ctfd_censored_writeups.publish import publish_submission
    c = make_challenge()
    sid = _make_submission(app, c.id)
    with app.app_context():
        sub = app.db.session.get(WriteupSubmission, sid)
        first = publish_submission(sub).id
        app.db.session.commit()
        sub = app.db.session.get(WriteupSubmission, sid)
        sub.title = "T2"
        again = publish_submission(sub).id
        app.db.session.commit()
        assert first == again
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").count() == 1
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").one().title == "T2"


def test_unpublish_removes_both_rows(app, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission, Writeup, WriteupUncensored
    from ctfd_censored_writeups.publish import publish_submission, unpublish_submission
    c = make_challenge()
    sid = _make_submission(app, c.id)
    with app.app_context():
        sub = app.db.session.get(WriteupSubmission, sid)
        w = publish_submission(sub)
        app.db.session.commit()
        wid = w.id
        unpublish_submission(sub)
        app.db.session.commit()
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is None
        assert WriteupUncensored.query.filter_by(writeup_id=wid).first() is None


def test_sync_leaves_submission_namespace_alone(app, make_challenge, tmp_path):
    """THE critical regression test for the one change to existing code: a full
    sync run must not delete published submissions (their source_key is not a
    file on disk)."""
    from ctfd_censored_writeups.models import WriteupSubmission, Writeup
    from ctfd_censored_writeups.publish import publish_submission
    from ctfd_censored_writeups.sync import sync_from_dir
    c = make_challenge()
    sid = _make_submission(app, c.id)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "a.md").write_text(f"---\nchallenge: {c.id}\ntitle: F\n---\nfile body\n")
    with app.app_context():
        sub = app.db.session.get(WriteupSubmission, sid)
        publish_submission(sub)
        app.db.session.commit()
        report = sync_from_dir(app, str(repo))
        assert report.deleted == 0
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is not None
        assert Writeup.query.filter_by(source_key="a.md").first() is not None
        # and the reverse: deleting the FILE still works
        (repo / "a.md").unlink()
        report = sync_from_dir(app, str(repo))
        assert report.deleted == 1
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is not None
