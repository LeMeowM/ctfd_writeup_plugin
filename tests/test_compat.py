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


def test_solved_challenges_lists_only_solved_sorted(app, make_user, make_challenge, make_solve):
    b = make_challenge(name="Bravo")
    a = make_challenge(name="Alpha")
    unsolved = make_challenge(name="Zulu")
    u = make_user()
    make_solve(user_id=u.id, challenge_id=b.id)
    make_solve(user_id=u.id, challenge_id=a.id)
    with app.app_context():
        got = compat.solved_challenges(u.id)
    assert got == [(a.id, "Alpha"), (b.id, "Bravo")]


def test_solved_challenges_none_account(app):
    with app.app_context():
        assert compat.solved_challenges(None) == []


def test_challenge_and_user_name_lookups(app, make_user, make_challenge):
    c = make_challenge(name="Named")
    u = make_user()
    with app.app_context():
        assert compat.challenge_name(c.id) == "Named"
        assert compat.challenge_name(99999) is None
        assert compat.user_name(u.id) == u.name
        assert compat.user_name(99999) is None
