import pathlib

DOC = "---\nchallenge: {c}\ntitle: T\n---\nintro <!--redact-->FLAG{{secret}}<!--/redact--> outro\n"


def test_assets_served(app):
    client = app.test_client()
    r = client.get("/plugins/ctfd_censored_writeups/assets/writeups.js")
    assert r.status_code == 200


def test_nav_link_registered(app):
    # In CTFd 3.7.6, the accessor is get_user_page_menu_bar in CTFd.plugins,
    # NOT get_registered_user_page_menu_bar in CTFd.utils.plugins (which does not exist).
    # get_user_page_menu_bar() calls url_for() which needs a request context for non-http
    # routes, so we inspect app.plugin_menu_bar directly (raw Menu namedtuples, .route is the
    # registered route string).
    with app.app_context():
        hrefs = [m.route for m in app.plugin_menu_bar]
    assert any("/writeups" in (h or "") for h in hrefs)


def test_writeups_index(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge()
    _seed(app, tmp_path, c.id)
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/writeups")
    assert r.status_code == 200
    # the index lists the challenge that has writeups...
    assert f"/writeups/{c.id}".encode() in r.data
    # ...but never any writeup body content (censored or uncensored)
    assert b"FLAG{secret}" not in r.data
    assert b"intro" not in r.data


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
    assert b">T</a>" in r.data             # title rendered as link text
    assert b"FLAG{secret}" not in r.data  # no body content


def test_api_single_unsolved_is_censored(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}/{wid}")
    assert "FLAG{secret}" not in r.get_json()["data"]["body"]
    assert r.headers["Cache-Control"] == "private, no-store"


def test_api_single_solved_is_uncensored(app, make_user, make_challenge, make_solve, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}/{wid}")
    assert "FLAG{secret}" in r.get_json()["data"]["body"]


def test_api_list_no_body(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
    for entry in body["data"]:
        assert "body" not in entry
    assert b"FLAG{secret}" not in r.data
