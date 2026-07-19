def test_submission_roundtrip_and_defaults(app):
    from ctfd_censored_writeups.models import WriteupSubmission, STATUS_PENDING
    with app.app_context():
        s = WriteupSubmission(challenge_id=1, user_id=2, account_id=2,
                              title="T", author="alice", body_raw="FLAG{x} body")
        app.db.session.add(s)
        app.db.session.commit()
        got = WriteupSubmission.query.one()
        assert got.status == STATUS_PENDING
        assert got.body_edited is None
        assert got.score is None
        assert got.llm_report is None
        assert got.writeup_id is None
        assert got.created_at is not None
        assert got.updated_at is not None


def test_submission_lives_in_uncensored_bind_only(app):
    """Raw bodies are presumed to contain flags: the table must exist in the
    uncensored bind and must NOT exist in the main DB."""
    import sqlalchemy
    from ctfd_censored_writeups.models import WriteupSubmission  # noqa: F401
    with app.app_context():
        main = sqlalchemy.inspect(app.db.get_engine(app))
        unc = sqlalchemy.inspect(app.db.get_engine(app, bind="uncensored"))
        assert "plugin_writeup_submissions" not in main.get_table_names()
        assert "plugin_writeup_submissions" in unc.get_table_names()


def test_one_live_submission_per_user_and_challenge(app):
    import pytest, sqlalchemy
    from ctfd_censored_writeups.models import WriteupSubmission
    with app.app_context():
        app.db.session.add(WriteupSubmission(challenge_id=1, user_id=2, account_id=2,
                                             title="a", author="a", body_raw="a"))
        app.db.session.commit()
        app.db.session.add(WriteupSubmission(challenge_id=1, user_id=2, account_id=2,
                                             title="b", author="b", body_raw="b"))
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            app.db.session.commit()
        app.db.session.rollback()
