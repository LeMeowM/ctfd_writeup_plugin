"""
tests/test_leak_matrix.py

End-to-end leak/gate matrix: the invariant that uncensored content
(flag and solve-script bytes) is absent from EVERY route for an
unsolved/non-admin requester.

Coverage:
  User mode (app fixture from conftest):
    - unsolved player: HTML list, HTML single, JSON list, JSON single,
      writeups index, 404 path
    - solved player: HTML single (positive control)
    - IDOR: solved B, writeup belongs to A → still censored

  Team mode (app_teams local fixture):
    - teammate's solve unlocks uncensored for the other team member
    - teamless user (no team_id) stays censored
"""

import os
import sys

import pytest

SECRET = "FLAG{do_not_leak}"

# The ```flag fence MUST start at the beginning of a line.
# The redaction regex uses ^/MULTILINE anchors, so inline ``` does NOT
# trigger fence-censoring. We split the f-string to keep the fence
# line-initial in the resulting string.
#
# We use "CHAL_ID" as a placeholder (not {c}) because FLAG{do_not_leak}
# contains literal braces that would confuse str.format().
DOC = (
    "---\nchallenge: CHAL_ID\ntitle: T\n---\n"
    f"intro <!--redact-->{SECRET}<!--/redact-->\n"
    "```flag\nsolve.py\n```\noutro\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed(app, tmp_path, cid, filename="a.md"):
    from ctfd_censored_writeups.sync import sync_from_dir
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / filename).write_text(DOC.replace("CHAL_ID", str(cid)))
    with app.app_context():
        sync_from_dir(app, str(repo))
        from ctfd_censored_writeups.models import Writeup
        return Writeup.query.filter_by(source_key=filename).one().id


def _assert_no_secret(resp):
    """Assert neither the flag string nor the solve-script filename leaks."""
    assert SECRET.encode() not in resp.data, (
        f"FLAG leaked on {resp.request.path if hasattr(resp, 'request') else '?'}"
    )
    assert b"solve.py" not in resp.data, (
        f"solve.py leaked on {resp.request.path if hasattr(resp, 'request') else '?'}"
    )


# ---------------------------------------------------------------------------
# User-mode tests (use conftest app fixture)
# ---------------------------------------------------------------------------

def test_unsolved_player_never_sees_secret_anywhere(
    app, make_user, make_challenge, tmp_path
):
    """Unsolved player: secret absent from every route variant."""
    from tests.helpers import login_as_user

    c = make_challenge()
    u = make_user()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")

    for url in (
        f"/writeups/{c.id}",             # HTML list
        f"/writeups/{c.id}/{wid}",       # HTML single
        f"/api/v1/writeups/{c.id}",      # JSON list
        f"/api/v1/writeups/{c.id}/{wid}",# JSON single
        "/writeups",                     # index
        f"/writeups/{c.id}/999999",      # 404 path
    ):
        resp = client.get(url)
        _assert_no_secret(resp)


def test_solved_player_sees_secret(
    app, make_user, make_challenge, make_solve, tmp_path
):
    """Solved player CAN see the flag on the HTML single route (positive control)."""
    from tests.helpers import login_as_user

    c = make_challenge()
    u = make_user()
    wid = _seed(app, tmp_path, c.id)
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert SECRET.encode() in client.get(f"/writeups/{c.id}/{wid}").data


def test_idor_cross_challenge_no_leak(
    app, make_user, make_challenge, make_solve, tmp_path
):
    """IDOR: user solved B, writeup row belongs to A → still censored."""
    from tests.helpers import login_as_user

    a = make_challenge(name="A")
    b = make_challenge(name="B")
    u = make_user()
    wid = _seed(app, tmp_path, a.id)
    make_solve(user_id=u.id, challenge_id=b.id)
    client = login_as_user(app, name=u.name, password="pw")
    _assert_no_secret(client.get(f"/writeups/{b.id}/{wid}"))


# ---------------------------------------------------------------------------
# Team-mode fixture + test
# ---------------------------------------------------------------------------

@pytest.fixture
def app_teams(tmp_path):
    """CTFd app configured with user_mode=teams for team-gate end-to-end tests."""
    old = {k: os.environ.get(k) for k in (
        "WRITEUPS_UNCENSORED_BIND_URI", "WRITEUPS_REPO_PATH", "WRITEUPS_WEBHOOK_SECRET"
    )}
    os.environ["WRITEUPS_UNCENSORED_BIND_URI"] = f"sqlite:///{tmp_path}/uncensored_teams.db"
    os.environ["WRITEUPS_REPO_PATH"] = str(tmp_path / "repo_teams")

    # Evict stale plugin modules so the new app gets a clean slate.
    for _k in [k for k in list(sys.modules)
               if k == "ctfd_censored_writeups" or k.startswith("ctfd_censored_writeups.")]:
        sys.modules.pop(_k, None)

    from tests.helpers import create_ctfd, destroy_ctfd

    app = create_ctfd(enable_plugins=True, user_mode="teams")

    # Wire top-level aliases (same pattern as conftest).
    _plugin_prefix = "CTFd.plugins.ctfd_censored_writeups"
    for _full_name in list(sys.modules):
        if _full_name == _plugin_prefix or _full_name.startswith(_plugin_prefix + "."):
            _alias = "ctfd_censored_writeups" + _full_name[len(_plugin_prefix):]
            sys.modules[_alias] = sys.modules[_full_name]

    yield app

    destroy_ctfd(app)
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    for _k in [k for k in list(sys.modules)
               if k == "ctfd_censored_writeups" or k.startswith("ctfd_censored_writeups.")]:
        sys.modules.pop(_k, None)


def test_team_mode_teammate_solve_unlocks_uncensored(app_teams, tmp_path):
    """
    Team mode end-to-end:
      - user_a solves the challenge (solve row carries team_id)
      - user_b (same team, no personal solve) sees uncensored via team solve
      - loner (no team) stays censored
    """
    from tests.helpers import login_as_user, gen_user, gen_challenge, gen_solve
    from CTFd.models import db, Teams

    with app_teams.app_context():
        # Build a minimal team with two members.
        team = Teams(name="t1", email="t1@x.io", password="pw")
        db.session.add(team)
        db.session.flush()  # populate team.id

        user_a = gen_user(db, name="player_a", email="pa@x.io",
                          password="pw", team_id=team.id)
        user_b = gen_user(db, name="player_b", email="pb@x.io",
                          password="pw", team_id=team.id)
        team.captain_id = user_a.id
        db.session.commit()

        chal = gen_challenge(db, name="C_tm")

        repo = tmp_path / "repo_tm"
        repo.mkdir(exist_ok=True)
        (repo / "tm.md").write_text(DOC.replace("CHAL_ID", str(chal.id)))
        from ctfd_censored_writeups.sync import sync_from_dir
        sync_from_dir(app_teams, str(repo))
        from ctfd_censored_writeups.models import Writeup
        wid = Writeup.query.filter_by(source_key="tm.md").one().id

        chal_id = chal.id
        team_id = team.id
        u_a_id = user_a.id
        u_a_name, u_b_name = user_a.name, user_b.name

    # Record the solve with team_id so has_solved(team_id, chal_id) is True.
    with app_teams.app_context():
        gen_solve(db, user_id=u_a_id, challenge_id=chal_id, team_id=team_id)

    # user_b (same team, didn't personally solve) → uncensored via team solve.
    client_b = login_as_user(app_teams, name=u_b_name, password="pw")
    resp_b = client_b.get(f"/writeups/{chal_id}/{wid}")
    assert SECRET.encode() in resp_b.data, (
        "teammate's solve must unlock uncensored content for the other team member"
    )

    # Teamless loner (team_id=None) → always censored.
    with app_teams.app_context():
        loner = gen_user(db, name="loner", email="loner@x.io", password="pw")
        loner_name = loner.name

    client_c = login_as_user(app_teams, name=loner_name, password="pw")
    _assert_no_secret(client_c.get(f"/writeups/{chal_id}/{wid}"))
