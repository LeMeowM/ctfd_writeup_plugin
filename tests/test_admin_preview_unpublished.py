"""Tests for Item 2: admin preview of unpublished (visible=False) writeups.

visible=False writeups are hidden from regular users but visible to admins
(spec §9 — admins can preview before publishing).
"""
import pathlib

DOC_VISIBLE = "---\nchallenge: {c}\ntitle: Published\n---\npublished body\n"
DOC_HIDDEN = "---\nchallenge: {c}\ntitle: Draft\nvisible: false\n---\ndraft body\n"


def _seed(app, tmp_path, challenge_id):
    """Seed one visible and one unpublished writeup for the challenge."""
    from ctfd_censored_writeups.sync import sync_from_dir
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "published.md").write_text(DOC_VISIBLE.format(c=challenge_id))
    (repo / "draft.md").write_text(DOC_HIDDEN.format(c=challenge_id))
    with app.app_context():
        sync_from_dir(app, str(repo))
        from ctfd_censored_writeups.models import Writeup
        visible_id = Writeup.query.filter_by(source_key="published.md").one().id
        draft_id = Writeup.query.filter_by(source_key="draft.md").one().id
        return visible_id, draft_id


# ---------------------------------------------------------------------------
# HTML single
# ---------------------------------------------------------------------------

def test_unpublished_single_404_for_user(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    _vis, draft = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}/{draft}")
    assert r.status_code == 404


def test_unpublished_single_200_for_admin(app, make_admin, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge()
    a = make_admin()
    _vis, draft = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=a.name, password="pw")
    r = client.get(f"/writeups/{c.id}/{draft}")
    assert r.status_code == 200
    assert b"Draft" in r.data


# ---------------------------------------------------------------------------
# JSON single
# ---------------------------------------------------------------------------

def test_unpublished_api_single_404_for_user(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    _vis, draft = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}/{draft}")
    assert r.status_code == 404


def test_unpublished_api_single_200_for_admin(app, make_admin, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge()
    a = make_admin()
    _vis, draft = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=a.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}/{draft}")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Listing / API list
# ---------------------------------------------------------------------------

def test_unpublished_absent_from_listing_for_user(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}")
    assert r.status_code == 200
    assert b">Draft</a>" not in r.data
    assert b">Published</a>" in r.data  # visible one still shows


def test_unpublished_present_in_listing_for_admin(app, make_admin, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge()
    a = make_admin()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=a.name, password="pw")
    r = client.get(f"/writeups/{c.id}")
    assert r.status_code == 200
    assert b">Draft</a>" in r.data


def test_unpublished_absent_from_api_list_for_user(app, make_user, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}")
    body = r.get_json()
    titles = [entry["title"] for entry in body["data"]]
    assert "Draft" not in titles
    assert "Published" in titles


def test_unpublished_present_in_api_list_for_admin(app, make_admin, make_challenge, tmp_path):
    from tests.helpers import login_as_user
    c = make_challenge()
    a = make_admin()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=a.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}")
    body = r.get_json()
    titles = [entry["title"] for entry in body["data"]]
    assert "Draft" in titles


# ---------------------------------------------------------------------------
# /writeups index
# ---------------------------------------------------------------------------

def test_challenge_with_only_unpublished_absent_from_index_for_user(app, make_user, make_challenge, tmp_path):
    """A challenge with ONLY unpublished writeups should not appear in the index for users."""
    from ctfd_censored_writeups.sync import sync_from_dir
    from tests.helpers import login_as_user
    c = make_challenge(name="only_draft")
    u = make_user()
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "draft_only.md").write_text(DOC_HIDDEN.format(c=c.id))
    with app.app_context():
        sync_from_dir(app, str(repo))
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/writeups")
    assert f"/writeups/{c.id}".encode() not in r.data


def test_challenge_with_only_unpublished_present_in_index_for_admin(app, make_admin, make_challenge, tmp_path):
    from ctfd_censored_writeups.sync import sync_from_dir
    from tests.helpers import login_as_user
    c = make_challenge(name="only_draft_admin")
    a = make_admin()
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "draft_only2.md").write_text(DOC_HIDDEN.format(c=c.id))
    with app.app_context():
        sync_from_dir(app, str(repo))
    client = login_as_user(app, name=a.name, password="pw")
    r = client.get("/writeups")
    assert f"/writeups/{c.id}".encode() in r.data
