import pathlib

DOC = "---\nchallenge: {c}\ntitle: T\n---\nintro <!--redact-->FLAG{{secret}}<!--/redact--> outro\n"

def _seed(app, tmp_path, challenge_id):
    from ctfd_censored_writeups.sync import sync_from_dir
    repo = tmp_path / "repo"; (repo).mkdir(exist_ok=True)
    (repo / "a.md").write_text(DOC.format(c=challenge_id))
    with app.app_context():
        sync_from_dir(app, str(repo))
        from ctfd_censored_writeups.models import Writeup
        return Writeup.query.filter_by(source_key="a.md").one().id

def test_unsolved_sees_censored(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}/{wid}")
    assert r.status_code == 200
    assert b"FLAG{secret}" not in r.data
    assert r.headers["Cache-Control"] == "private, no-store"

def test_solved_sees_uncensored(app, make_user, make_challenge, make_solve, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}/{wid}")
    assert b"FLAG{secret}" in r.data

def test_idor_uses_row_challenge_not_url(app, make_user, make_challenge, make_solve, tmp_path):
    # Writeup belongs to challenge A; user solved only B; URL lies with B's id.
    from tests.helpers import login_as_user
    a = make_challenge(name="A"); b = make_challenge(name="B"); u = make_user()
    wid = _seed(app, tmp_path, a.id)
    make_solve(user_id=u.id, challenge_id=b.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{b.id}/{wid}")   # attacker passes solved B's id
    assert r.status_code == 200                  # route returns 200 (not a stray 404)
    assert b"FLAG{secret}" not in r.data         # still censored: row says A

def test_404_on_writeup_route_carries_cache_control(app, make_user, make_challenge, tmp_path):
    """abort(404) from a writeup route must still set Cache-Control: private, no-store."""
    from tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}/99999")   # non-existent writeup id
    assert r.status_code == 404
    assert r.headers.get("Cache-Control") == "private, no-store"
