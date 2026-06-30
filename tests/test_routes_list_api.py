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


def test_list_shows_metadata_not_body(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}")
    assert r.status_code == 200
    assert b"T" in r.data                 # title present
    assert b"FLAG{secret}" not in r.data  # no body content


def test_api_single_unsolved_is_censored(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}/{wid}")
    data = r.get_json()
    assert "FLAG{secret}" not in data["body"]
    assert r.headers["Cache-Control"] == "private, no-store"


def test_api_single_solved_is_uncensored(app, make_user, make_challenge, make_solve, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}/{wid}")
    assert "FLAG{secret}" in r.get_json()["body"]
