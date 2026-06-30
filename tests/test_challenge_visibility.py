"""Tests for Item 1: challenge visibility enforcement on all writeup routes.

Non-admin users must NOT see writeups (even censored) for hidden challenges.
Admin users bypass this gate and can view writeups for hidden challenges.
"""
import pathlib

DOC = "---\nchallenge: {c}\ntitle: T\n---\nintro body text\n"


def _seed(app, tmp_path, challenge_id):
    from ctfd_censored_writeups.sync import sync_from_dir
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "a.md").write_text(DOC.format(c=challenge_id))
    with app.app_context():
        sync_from_dir(app, str(repo))
        from ctfd_censored_writeups.models import Writeup
        return Writeup.query.filter_by(source_key="a.md").one().id


# ---------------------------------------------------------------------------
# HTML single route
# ---------------------------------------------------------------------------

def test_hidden_challenge_single_404_for_user(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(name="hidden_chal", state="hidden")
    u = make_user()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}/{wid}")
    assert r.status_code == 404


def test_hidden_challenge_single_200_for_admin(app, make_admin, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(name="hidden_chal_admin", state="hidden")
    a = make_admin()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=a.name, password="pw")
    r = client.get(f"/writeups/{c.id}/{wid}")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# JSON single route
# ---------------------------------------------------------------------------

def test_hidden_challenge_api_single_404_for_user(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(name="hidden_api_single", state="hidden")
    u = make_user()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}/{wid}")
    assert r.status_code == 404


def test_hidden_challenge_api_single_200_for_admin(app, make_admin, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(name="hidden_api_single_admin", state="hidden")
    a = make_admin()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=a.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}/{wid}")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# HTML list route
# ---------------------------------------------------------------------------

def test_hidden_challenge_list_empty_for_user(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(name="hidden_list", state="hidden")
    u = make_user()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}")
    assert r.status_code == 200
    assert b"intro body text" not in r.data
    # The writeup title link should NOT appear for a hidden-challenge writeup
    assert b">T</a>" not in r.data


def test_hidden_challenge_list_shown_for_admin(app, make_admin, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(name="hidden_list_admin", state="hidden")
    a = make_admin()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=a.name, password="pw")
    r = client.get(f"/writeups/{c.id}")
    assert r.status_code == 200
    assert b">T</a>" in r.data


# ---------------------------------------------------------------------------
# JSON list route
# ---------------------------------------------------------------------------

def test_hidden_challenge_api_list_empty_for_user(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(name="hidden_api_list", state="hidden")
    u = make_user()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["success"] is True
    assert body["data"] == []


def test_hidden_challenge_api_list_nonempty_for_admin(app, make_admin, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(name="hidden_api_list_admin", state="hidden")
    a = make_admin()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=a.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}")
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["data"]) == 1


# ---------------------------------------------------------------------------
# /writeups index
# ---------------------------------------------------------------------------

def test_hidden_challenge_absent_from_index_for_user(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(name="hidden_index", state="hidden")
    u = make_user()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/writeups")
    assert r.status_code == 200
    assert f"/writeups/{c.id}".encode() not in r.data


def test_hidden_challenge_present_in_index_for_admin(app, make_admin, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge(name="hidden_index_admin", state="hidden")
    a = make_admin()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=a.name, password="pw")
    r = client.get("/writeups")
    assert r.status_code == 200
    assert f"/writeups/{c.id}".encode() in r.data
