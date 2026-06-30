def test_writeup_roundtrip(app):
    from ctfd_censored_writeups.models import Writeup, WriteupUncensored
    with app.app_context():
        w = Writeup(source_key="crypto/rsa.md", challenge_id=1,
                    title="t", censored_body="safe", sort_order=5, visible=True)
        app.db.session.add(w)
        app.db.session.commit()
        u = WriteupUncensored(writeup_id=w.id, uncensored_body="FLAG{x}")
        app.db.session.add(u)
        app.db.session.commit()

        got = Writeup.query.filter_by(source_key="crypto/rsa.md").one()
        assert got.censored_body == "safe"
        assert got.quarantined is False
        gu = WriteupUncensored.query.filter_by(writeup_id=w.id).one()
        assert gu.uncensored_body == "FLAG{x}"

def test_source_key_unique(app):
    from ctfd_censored_writeups.models import Writeup
    with app.app_context():
        app.db.session.add(Writeup(source_key="dup", censored_body="a"))
        app.db.session.commit()
        app.db.session.add(Writeup(source_key="dup", censored_body="b"))
        import pytest, sqlalchemy
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            app.db.session.commit()
