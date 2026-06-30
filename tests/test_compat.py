from ctfd_censored_writeups import compat

def test_resolve_by_numeric_id(app, make_challenge):
    chal = make_challenge(name="rsa")
    with app.app_context():
        assert compat.resolve_challenge_id(str(chal.id)) == chal.id

def test_resolve_by_name(app, make_challenge):
    chal = make_challenge(name="UniqueName")
    with app.app_context():
        assert compat.resolve_challenge_id("UniqueName") == chal.id

def test_resolve_unknown_returns_none(app):
    with app.app_context():
        assert compat.resolve_challenge_id("nope") is None

def test_has_solved_reflects_solve(app, make_user, make_challenge, make_solve):
    u = make_user(); c = make_challenge()
    with app.app_context():
        assert compat.has_solved(u.account_id, c.id) is False
    make_solve(user_id=u.id, challenge_id=c.id)
    with app.app_context():
        assert compat.has_solved(u.account_id, c.id) is True
