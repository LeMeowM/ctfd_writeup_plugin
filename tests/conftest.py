import os
import pathlib
import sys
import pytest

# Make the repo importable AND visible to CTFd's plugin loader by symlinking
# the repo into the installed CTFd's plugins directory.
REPO = pathlib.Path(__file__).resolve().parent.parent

# Make the repo root importable so pure-Python modules (e.g. redaction) can be
# imported standalone as `ctfd_censored_writeups.<mod>` at collection time,
# without the CTFd app/DB fixtures. Safe because importing the package only
# pulls in flask + config (no SQLAlchemy model registration); model tests still
# import `.models` lazily via the app-fixture alias to avoid double mapping.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

def _link_plugin():
    import CTFd
    plugins_dir = pathlib.Path(CTFd.__file__).resolve().parent / "plugins"
    link = plugins_dir / "ctfd_censored_writeups"
    if link.is_symlink() or link.exists():
        return
    link.symlink_to(REPO / "ctfd_censored_writeups", target_is_directory=True)

_link_plugin()

import CTFd as _CTFd
# ADAPTATION: CTFd 3.7.6 ships helpers as tests/helpers.py under its project
# root, NOT inside the CTFd package. A site-packages `tests` package (from
# pybluemonday) shadows it. We insert .ctfd-src at position 0 and evict any
# cached `tests.*` modules so Python reloads from the correct location.
_CTFD_SRC = str(pathlib.Path(_CTFd.__file__).resolve().parent.parent)
# ctfd.pth adds _CTFD_SRC to sys.path but AFTER site-packages, so the wrong
# `tests` package (from pybluemonday in site-packages) wins. Move it to front.
if _CTFD_SRC in sys.path:
    sys.path.remove(_CTFD_SRC)
sys.path.insert(0, _CTFD_SRC)
# Evict any cached tests.* that were imported from site-packages.
for _k in list(sys.modules.keys()):
    if _k == "tests" or _k.startswith("tests."):
        del sys.modules[_k]
from tests.helpers import create_ctfd, destroy_ctfd, gen_user, gen_team, gen_challenge, gen_solve, register_user, login_as_user  # noqa: E402


@pytest.fixture
def app(tmp_path):
    old = {k: os.environ.get(k) for k in ("WRITEUPS_UNCENSORED_BIND_URI", "WRITEUPS_REPO_PATH")}
    os.environ["WRITEUPS_UNCENSORED_BIND_URI"] = f"sqlite:///{tmp_path}/uncensored.db"
    os.environ["WRITEUPS_REPO_PATH"] = str(tmp_path / "repo")
    # Evict any stale repo-root copies of the plugin loaded at collection time
    # so CTFd's plugin loader registers a clean copy against its own DB session.
    import sys as _sys
    for _k in [k for k in list(_sys.modules)
               if k == "ctfd_censored_writeups" or k.startswith("ctfd_censored_writeups.")]:
        _sys.modules.pop(_k, None)
    # enable_plugins=True is required so CTFd sets SAFE_MODE=False and calls
    # init_plugins(), which discovers and loads ctfd_censored_writeups.
    app = create_ctfd(enable_plugins=True)
    # Wire top-level alias so tests can do: from ctfd_censored_writeups.models import ...
    # without triggering a second SQLAlchemy table registration.
    # Force-overwrite (not setdefault) so a stale repo-root entry can't win.
    _plugin_prefix = "CTFd.plugins.ctfd_censored_writeups"
    for _full_name in list(_sys.modules):
        if _full_name == _plugin_prefix or _full_name.startswith(_plugin_prefix + "."):
            _alias = "ctfd_censored_writeups" + _full_name[len(_plugin_prefix):]
            _sys.modules[_alias] = _sys.modules[_full_name]
    yield app
    destroy_ctfd(app)
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    import sys as _sys
    for _k in [k for k in list(_sys.modules) if k == "ctfd_censored_writeups" or k.startswith("ctfd_censored_writeups.")]:
        _sys.modules.pop(_k, None)


def _eager_load(obj, *attrs):
    """Access attributes while in-session so they're cached before detachment."""
    for attr in attrs:
        getattr(obj, attr, None)
    return obj


@pytest.fixture
def make_admin(app):
    def _make(name="admin", email="admin@x.io"):
        with app.app_context():
            u = gen_user(app.db, name=name, email=email, password="pw", type="admin")
            return _eager_load(u, "id", "name", "email", "type")
    return _make


@pytest.fixture
def make_user(app):
    def _make(name="player", email="p@x.io"):
        with app.app_context():
            u = gen_user(app.db, name=name, email=email, password="pw")
            return _eager_load(u, "id", "name", "email", "type")
    return _make


@pytest.fixture
def make_team(app):
    def _make(name="team1"):
        with app.app_context():
            t = gen_team(app.db, name=name)
            return _eager_load(t, "id", "name", "email")
    return _make


@pytest.fixture
def make_challenge(app):
    def _make(name="chal", value=100):
        with app.app_context():
            c = gen_challenge(app.db, name=name, value=value)
            return _eager_load(c, "id", "name", "value", "category", "type", "state")
    return _make


@pytest.fixture
def make_solve(app):
    def _make(user_id, challenge_id, team_id=None):
        with app.app_context():
            s = gen_solve(app.db, user_id=user_id, challenge_id=challenge_id, team_id=team_id)
            return _eager_load(s, "id", "user_id", "challenge_id", "team_id")
    return _make
