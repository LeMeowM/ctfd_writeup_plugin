# CTFd Censored-Writeups Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CTFd plugin that serves censored writeups (flag + solve script redacted) to players who haven't solved a challenge and uncensored writeups to those who have, sourced from an external git repo of markdown.

**Architecture:** Five isolated units — `redaction` (pure markdown stripper), `parser` (frontmatter/file reader), `compat` (the only place CTFd version-specific APIs are touched), `gate` (solve decision), `sync` (git → DB upsert) — wired into CTFd through `models`, `views`, `cli`, and `__init__.load`. Uncensored bodies live in a separate SQLAlchemy bind the unsolved request path never opens. The single invariant: uncensored bytes never leave the server for a request that hasn't passed the solve check.

**Tech Stack:** Python 3.11+, CTFd 3.7.6 (Flask + SQLAlchemy), pytest, PyYAML, GitPython.

## Global Constraints

- **Target CTFd version:** 3.7.6 exactly. Pin in `requirements-dev.txt`.
- **The invariant:** uncensored content (flag + solve script) must be physically absent from every response — HTML, JSON, and error pages — for any request that has not passed the solve check. Server-side gate only; never hide via CSS/JS.
- **Bind isolation:** uncensored bodies live only in the `uncensored` bind. Code on the unsolved path must never query `WriteupUncensored`.
- **CTFd API names** (`get_model`, `is_teams_mode`, `account_id`, `Solves` columns, decorator import paths) are touched ONLY in `compat.py`. Every such name is verified against the installed `CTFd/` source before use; no other module imports from `CTFd.*` except `models.py`, `views.py`, `cli.py`, and `__init__.py`.
- **Fail closed:** any redaction parse ambiguity (unclosed/nested/malformed markers) redacts the remainder rather than leaking it.
- **TDD:** every task writes the failing test first, watches it fail, then implements. Commit after each green task.
- **Package name:** `ctfd_censored_writeups` (the repo IS the plugin directory; it is symlinked into `CTFd/plugins/` for tests).

---

## File Structure

```
ctfd_censored_writeups/            # repo root = plugin package
  __init__.py                      # load(app): register models, blueprint, assets, nav, cli
  config.py                        # plugin config keys + reads from CTFd config / env
  redaction.py                     # pure: censor(markdown:str) -> CensorResult
  parser.py                        # pure: parse_writeup_file(text:str, path:str) -> ParsedWriteup
  compat.py                        # ONLY CTFd-version-specific glue (solve check, mode, ctf-ended)
  gate.py                          # decide(user, challenge_id) -> Decision
  models.py                        # Writeup (main db), WriteupUncensored (uncensored bind)
  sync.py                          # sync_repo(...) -> SyncReport ; upsert/delete/quarantine
  cli.py                           # `flask writeups sync` command
  views.py                         # blueprint: list, single, api, webhook, admin page
  assets/                          # self-contained page CSS/JS
    writeups.css
    writeups.js
  templates/
    writeups_list.html
    writeup_single.html
    admin_writeups.html
  docs/
    writeup-format.md              # authoring docs (file structure)
    how-it-works.md                # gate, storage, sync, quarantine
    operator-setup.md              # binds, webhook secret, post-CTF toggle, seeding
tests/
  conftest.py                      # symlink plugin into CTFd, app fixture, factories
  test_redaction.py
  test_parser.py
  test_compat.py
  test_gate.py
  test_models.py
  test_sync.py
  test_cli.py
  test_routes_single.py
  test_routes_list_api.py
  test_webhook.py
  test_leak_matrix.py              # the invariant, end-to-end
requirements.txt                   # runtime deps (PyYAML, GitPython)
requirements-dev.txt               # CTFd==3.7.6, pytest, etc.
README.md
```

---

### Task 0: Environment, dependencies, and plugin scaffold

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `ctfd_censored_writeups/__init__.py`, `ctfd_censored_writeups/config.py`, `tests/conftest.py`, `pytest.ini`
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Produces: importable package `ctfd_censored_writeups` with `load(app)`; a pytest `app` fixture that boots CTFd 3.7.6 with the plugin loaded; factory fixtures `make_user`, `make_admin`, `make_team`, `make_challenge`, `make_solve`.

- [ ] **Step 1: Write dependency files**

`requirements.txt`:
```
PyYAML>=6.0
GitPython>=3.1
```
`requirements-dev.txt`:
```
-r requirements.txt
CTFd==3.7.6
pytest>=8.0
```

- [ ] **Step 2: Create venv and install**

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```
Expected: CTFd 3.7.6 and deps install. Note the install path: `.venv/lib/python3.*/site-packages/CTFd`.

- [ ] **Step 3: Read the pinned CTFd source for the names compat.py will need**

Run (record findings as comments in `compat.py` later):
```bash
PKG=$(.venv/bin/python -c "import CTFd, os; print(os.path.dirname(CTFd.__file__))")
grep -rn "def get_model" $PKG/utils/modes/__init__.py
grep -rn "def is_teams_mode" $PKG/utils/config/__init__.py $PKG/utils/modes/__init__.py
grep -rn "account_id" $PKG/models/__init__.py | head
grep -rn "def get_current_user\b" $PKG/utils/user/__init__.py
grep -rn "authed_only\|admins_only\|during_ctf_time_only" $PKG/utils/decorators/__init__.py
grep -rn "register_plugin_assets_directory\|register_user_page_menu_bar\|register_plugin_script" $PKG/plugins/__init__.py
```
Expected: confirm the import paths and attribute names. These are the ONLY CTFd internals the plugin depends on; everything else is plugin-owned.

- [ ] **Step 4: Write the failing scaffold test**

`tests/test_scaffold.py`:
```python
def test_plugin_loads(app):
    # The plugin registered its blueprint under the name "writeups".
    assert "writeups" in app.blueprints

def test_factories(make_admin, make_challenge):
    admin = make_admin()
    chal = make_challenge(name="rsa")
    assert admin.type == "admin"
    assert chal.id is not None
```

- [ ] **Step 5: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_scaffold.py -v`
Expected: FAIL (no `app` fixture / plugin not importable).

- [ ] **Step 6: Write the minimal plugin package**

`ctfd_censored_writeups/config.py`:
```python
import os

# Plugin config keys (read from app.config first, then env, then default).
DEFAULTS = {
    "WRITEUPS_REPO_PATH": "/data/writeups-repo",   # local working copy synced from git
    "WRITEUPS_WEBHOOK_SECRET": "",                  # HMAC secret; empty disables webhook
    "WRITEUPS_OPEN_AFTER_CTF": False,               # post-CTF toggle; default keep gate
    "WRITEUPS_UNCENSORED_BIND_URI": "sqlite:////data/uncensored.db",
}

def get(app, key):
    if key in app.config and app.config[key] not in (None, ""):
        return app.config[key]
    env = os.environ.get(key)
    if env is not None:
        return env
    return DEFAULTS[key]
```

`ctfd_censored_writeups/__init__.py`:
```python
from flask import Blueprint
from .config import get


def load(app):
    # Register the uncensored bind BEFORE models import / create_all.
    binds = app.config.setdefault("SQLALCHEMY_BINDS", {})
    binds["uncensored"] = get(app, "WRITEUPS_UNCENSORED_BIND_URI")

    from .models import Writeup, WriteupUncensored  # noqa: F401  (registers mappers)
    from CTFd.models import db
    app.db.create_all()  # materializes both the default and uncensored binds

    blueprint = Blueprint(
        "writeups", __name__, template_folder="templates", static_folder="assets"
    )
    from . import views
    views.register(blueprint)
    app.register_blueprint(blueprint)

    from . import cli
    cli.register(app)
```

- [ ] **Step 7: Write the test harness**

`pytest.ini`:
```ini
[pytest]
addopts = -p no:cacheprovider
```

`tests/conftest.py`:
```python
import os
import pathlib
import pytest

# Make the repo importable AND visible to CTFd's plugin loader by symlinking
# the repo into the installed CTFd's plugins directory.
REPO = pathlib.Path(__file__).resolve().parent.parent

def _link_plugin():
    import CTFd
    plugins_dir = pathlib.Path(CTFd.__file__).resolve().parent / "plugins"
    link = plugins_dir / "ctfd_censored_writeups"
    if link.is_symlink() or link.exists():
        return
    link.symlink_to(REPO / "ctfd_censored_writeups", target_is_directory=True)

_link_plugin()

from CTFd.tests.helpers import create_ctfd, destroy_ctfd, gen_user, gen_team, gen_challenge, gen_solve, register_user, login_as_user  # noqa: E402


@pytest.fixture
def app(tmp_path):
    os.environ["WRITEUPS_UNCENSORED_BIND_URI"] = f"sqlite:///{tmp_path}/uncensored.db"
    os.environ["WRITEUPS_REPO_PATH"] = str(tmp_path / "repo")
    app = create_ctfd()
    yield app
    destroy_ctfd(app)


@pytest.fixture
def make_admin(app):
    def _make(name="admin", email="admin@x.io"):
        with app.app_context():
            return gen_user(app.db, name=name, email=email, password="pw", type="admin")
    return _make


@pytest.fixture
def make_user(app):
    def _make(name="player", email="p@x.io"):
        with app.app_context():
            return gen_user(app.db, name=name, email=email, password="pw")
    return _make


@pytest.fixture
def make_team(app):
    def _make(name="team1"):
        with app.app_context():
            return gen_team(app.db, name=name)
    return _make


@pytest.fixture
def make_challenge(app):
    def _make(name="chal", value=100):
        with app.app_context():
            return gen_challenge(app.db, name=name, value=value)
    return _make


@pytest.fixture
def make_solve(app):
    def _make(user_id, challenge_id, team_id=None):
        with app.app_context():
            return gen_solve(app.db, user_id=user_id, challenge_id=challenge_id, team_id=team_id)
    return _make
```

> If `gen_user`/`gen_solve` signatures differ in 3.7.6, adjust to the names found in `CTFd/tests/helpers.py` (read it; it is the canonical test API for the pinned version).

- [ ] **Step 8: Stub views/cli/models so the app boots**

`ctfd_censored_writeups/views.py`:
```python
def register(blueprint):
    pass  # routes added in later tasks
```
`ctfd_censored_writeups/cli.py`:
```python
def register(app):
    pass  # command added in Task 7
```
`ctfd_censored_writeups/models.py`:
```python
from CTFd.models import db


class Writeup(db.Model):
    __tablename__ = "plugin_writeups"
    id = db.Column(db.Integer, primary_key=True)


class WriteupUncensored(db.Model):
    __bind_key__ = "uncensored"
    __tablename__ = "plugin_writeups_uncensored"
    id = db.Column(db.Integer, primary_key=True)
```

- [ ] **Step 9: Run the scaffold test to verify it passes**

Run: `.venv/bin/pytest tests/test_scaffold.py -v`
Expected: PASS (2 tests).

- [ ] **Step 10: Commit**

```bash
git add requirements.txt requirements-dev.txt pytest.ini ctfd_censored_writeups tests/conftest.py tests/test_scaffold.py
git commit -m "feat: scaffold plugin, CTFd 3.7.6 test harness, uncensored bind"
```

---

### Task 1: Data models

**Files:**
- Modify: `ctfd_censored_writeups/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `Writeup(id, challenge_id:int|None, source_key:str, title:str, author:str|None, censored_body:str, sort_order:int, tags:str|None, language:str|None, visible:bool, quarantined:bool, created_at, updated_at)` in the default bind.
  - `WriteupUncensored(writeup_id:int [pk], uncensored_body:str)` in the `uncensored` bind.
  - `source_key` is UNIQUE (stable identity for idempotent sync).

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: FAIL (columns don't exist).

- [ ] **Step 3: Implement the models**

`ctfd_censored_writeups/models.py`:
```python
from datetime import datetime
from CTFd.models import db


class Writeup(db.Model):
    __tablename__ = "plugin_writeups"

    id = db.Column(db.Integer, primary_key=True)
    source_key = db.Column(db.String(512), unique=True, nullable=False, index=True)
    challenge_id = db.Column(db.Integer, nullable=True, index=True)
    title = db.Column(db.Text, nullable=False, default="")
    author = db.Column(db.Text, nullable=True)
    censored_body = db.Column(db.Text, nullable=False, default="")
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    tags = db.Column(db.Text, nullable=True)        # comma-joined
    language = db.Column(db.String(16), nullable=True)
    visible = db.Column(db.Boolean, nullable=False, default=True)
    quarantined = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WriteupUncensored(db.Model):
    __bind_key__ = "uncensored"
    __tablename__ = "plugin_writeups_uncensored"

    writeup_id = db.Column(db.Integer, primary_key=True)  # no cross-bind FK by design
    uncensored_body = db.Column(db.Text, nullable=False, default="")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/models.py tests/test_models.py
git commit -m "feat: Writeup + WriteupUncensored models across two binds"
```

---

### Task 2: Redaction (pure, safety-critical)

**Files:**
- Create: `ctfd_censored_writeups/redaction.py`
- Test: `tests/test_redaction.py`

**Interfaces:**
- Produces:
  - `PLACEHOLDER_INLINE = "〔redacted — solve this challenge to view〕"`
  - `PLACEHOLDER_BLOCK` (a fenced placeholder block string)
  - `@dataclass CensorResult(censored: str, redacted_spans: int, ok: bool)`
  - `censor(markdown: str) -> CensorResult` — strips `<!--redact-->...<!--/redact-->` inline spans and ```` ```flag ````/```` ```spoiler ```` fenced blocks; fails closed.
  - `verify_no_secret(censored: str) -> bool` — True if no marker remnants remain.

- [ ] **Step 1: Write the failing tests**

`tests/test_redaction.py`:
```python
from ctfd_censored_writeups.redaction import censor, verify_no_secret, PLACEHOLDER_INLINE

def test_inline_span_removed():
    r = censor("intended path was <!--redact-->the LSB oracle<!--/redact--> here")
    assert "LSB oracle" not in r.censored
    assert PLACEHOLDER_INLINE in r.censored
    assert r.redacted_spans == 1
    assert r.ok

def test_flag_fence_contents_stripped():
    src = "before\n```flag\npython solve.py\nFLAG{x}\n```\nafter"
    r = censor(src)
    assert "FLAG{x}" not in r.censored
    assert "solve.py" not in r.censored
    assert "before" in r.censored and "after" in r.censored

def test_spoiler_fence_stripped():
    r = censor("```spoiler\nsecret approach\n```")
    assert "secret approach" not in r.censored

def test_unclosed_inline_fails_closed():
    # No closing marker: everything from the open marker on is treated as redacted.
    r = censor("safe text <!--redact-->leaking secret to end")
    assert "leaking secret" not in r.censored
    assert r.ok is False  # signals the author to fix the source

def test_nested_markers_fail_closed():
    r = censor("<!--redact-->a<!--redact-->b<!--/redact-->c<!--/redact-->")
    assert "a" not in r.censored and "b" not in r.censored
    assert r.ok is False

def test_verify_detects_remnant():
    assert verify_no_secret("clean text") is True
    assert verify_no_secret("oops <!--redact--> leftover") is False

def test_no_markers_is_identity():
    src = "# Title\n\nplain body\n"
    r = censor(src)
    assert r.censored == src
    assert r.redacted_spans == 0 and r.ok
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_redaction.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement redaction**

`ctfd_censored_writeups/redaction.py`:
```python
import re
from dataclasses import dataclass

PLACEHOLDER_INLINE = "〔redacted — solve this challenge to view〕"
PLACEHOLDER_BLOCK = "```\n〔redacted — solve this challenge to view〕\n```"

_OPEN = "<!--redact-->"
_CLOSE = "<!--/redact-->"
# Fenced block whose info string is exactly `flag` or `spoiler`.
_FENCE = re.compile(r"^```(?:flag|spoiler)\s*$.*?^```\s*$", re.DOTALL | re.MULTILINE)


@dataclass
class CensorResult:
    censored: str
    redacted_spans: int
    ok: bool


def censor(markdown: str) -> CensorResult:
    ok = True
    spans = 0

    # 1) Fenced flag/spoiler blocks -> placeholder block.
    def _fence_sub(_m):
        nonlocal spans
        spans += 1
        return PLACEHOLDER_BLOCK

    text = _FENCE.sub(_fence_sub, markdown)

    # 2) Inline redact spans. Walk manually to fail closed on malformed input.
    out = []
    i = 0
    n = len(text)
    while i < n:
        start = text.find(_OPEN, i)
        if start == -1:
            out.append(text[i:])
            break
        out.append(text[i:start])
        # find matching close AFTER the open; reject nesting (another open first).
        close = text.find(_CLOSE, start + len(_OPEN))
        next_open = text.find(_OPEN, start + len(_OPEN))
        if close == -1 or (next_open != -1 and next_open < close):
            # Unclosed or nested: redact from here to end, mark not-ok.
            out.append(PLACEHOLDER_INLINE)
            spans += 1
            ok = False
            i = n
            break
        out.append(PLACEHOLDER_INLINE)
        spans += 1
        i = close + len(_CLOSE)

    censored = "".join(out)
    if not verify_no_secret(censored):
        ok = False
    return CensorResult(censored=censored, redacted_spans=spans, ok=ok)


def verify_no_secret(censored: str) -> bool:
    return _OPEN not in censored and _CLOSE not in censored and not _FENCE.search(censored)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_redaction.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/redaction.py tests/test_redaction.py
git commit -m "feat: fail-closed redaction of inline spans and flag/spoiler fences"
```

---

### Task 3: Writeup file parser (pure)

**Files:**
- Create: `ctfd_censored_writeups/parser.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Produces:
  - `@dataclass ParsedWriteup(source_key, challenge_ref:str, title, author, sort_order:int, tags:list[str], language:str|None, visible:bool, uncensored_body:str, censored_body:str, ok:bool)`
  - `parse_writeup_file(text: str, source_key: str) -> ParsedWriteup` — splits YAML frontmatter from body, runs `redaction.censor` on the body, carries `challenge_ref` as the raw frontmatter `challenge` value (string).
- Consumes: `redaction.censor`.

- [ ] **Step 1: Write the failing tests**

`tests/test_parser.py`:
```python
from ctfd_censored_writeups.parser import parse_writeup_file

DOC = """---
challenge: 42
title: Unintended RSA
author: alice
sort_order: 10
tags: [crypto, rsa]
visible: true
---
body before <!--redact-->secret<!--/redact--> after
"""

def test_parses_frontmatter_and_censors_body():
    p = parse_writeup_file(DOC, "crypto/rsa.md")
    assert p.source_key == "crypto/rsa.md"
    assert p.challenge_ref == "42"
    assert p.title == "Unintended RSA"
    assert p.author == "alice"
    assert p.sort_order == 10
    assert p.tags == ["crypto", "rsa"]
    assert p.visible is True
    assert "secret" in p.uncensored_body
    assert "secret" not in p.censored_body
    assert p.ok

def test_string_challenge_ref_preserved():
    doc = "---\nchallenge: My Challenge Name\ntitle: t\n---\nbody"
    p = parse_writeup_file(doc, "x.md")
    assert p.challenge_ref == "My Challenge Name"

def test_missing_frontmatter_is_not_ok():
    p = parse_writeup_file("just a body, no frontmatter", "x.md")
    assert p.ok is False
    assert p.challenge_ref == ""

def test_defaults_applied():
    p = parse_writeup_file("---\nchallenge: 1\ntitle: t\n---\nb", "x.md")
    assert p.sort_order == 0
    assert p.visible is True
    assert p.tags == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_parser.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the parser**

`ctfd_censored_writeups/parser.py`:
```python
from dataclasses import dataclass, field
import yaml
from .redaction import censor

_FM = "---"


@dataclass
class ParsedWriteup:
    source_key: str
    challenge_ref: str
    title: str
    author: str | None
    sort_order: int
    tags: list[str] = field(default_factory=list)
    language: str | None = None
    visible: bool = True
    uncensored_body: str = ""
    censored_body: str = ""
    ok: bool = True


def _split_frontmatter(text: str):
    stripped = text.lstrip()
    if not stripped.startswith(_FM):
        return None, text
    rest = stripped[len(_FM):]
    end = rest.find("\n" + _FM)
    if end == -1:
        return None, text
    fm = rest[:end]
    body = rest[end + len("\n" + _FM):].lstrip("\n")
    try:
        data = yaml.safe_load(fm) or {}
    except yaml.YAMLError:
        return None, text
    if not isinstance(data, dict):
        return None, text
    return data, body


def parse_writeup_file(text: str, source_key: str) -> ParsedWriteup:
    data, body = _split_frontmatter(text)
    ok = True
    if data is None:
        data = {}
        ok = False  # missing/invalid frontmatter -> quarantine upstream

    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    c = censor(body)
    if not c.ok:
        ok = False

    return ParsedWriteup(
        source_key=source_key,
        challenge_ref=str(data.get("challenge", "")).strip(),
        title=str(data.get("title", "")).strip(),
        author=(str(data["author"]).strip() if data.get("author") else None),
        sort_order=int(data.get("sort_order", 0) or 0),
        tags=[str(t) for t in tags],
        language=(str(data["language"]) if data.get("language") else None),
        visible=bool(data.get("visible", True)),
        uncensored_body=body,
        censored_body=c.censored,
        ok=ok,
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_parser.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/parser.py tests/test_parser.py
git commit -m "feat: writeup file parser (frontmatter + derived censoring)"
```

---

### Task 4: CTFd compatibility shim

**Files:**
- Create: `ctfd_censored_writeups/compat.py`
- Test: `tests/test_compat.py`

**Interfaces:**
- Produces (the ONLY functions allowed to touch CTFd version-specific internals):
  - `current_user()` -> CTFd user object or None
  - `is_admin(user) -> bool`
  - `account_id_for(user) -> int | None` (user id in user mode; team id in team mode; None if team mode and no team)
  - `has_solved(account_id: int, challenge_id: int) -> bool`
  - `ctf_ended() -> bool`
  - `challenge_exists(challenge_id: int) -> bool`
  - `resolve_challenge_id(challenge_ref: str) -> int | None` (numeric ref -> id if exists; else match `Challenges.name`; None/ambiguous -> None)

- [ ] **Step 1: Write the failing tests**

`tests/test_compat.py`:
```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_compat.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the shim — verifying every name against installed CTFd 3.7.6**

> Before writing, confirm the import paths from Task 0 Step 3. The code below targets 3.7.6; if a name differs in your checkout, change it HERE and nowhere else.

`ctfd_censored_writeups/compat.py`:
```python
from CTFd.models import db, Solves, Challenges, Users
from CTFd.utils.user import get_current_user
from CTFd.utils.config import is_teams_mode
from CTFd.utils import config as ctfd_config


def current_user():
    return get_current_user()


def is_admin(user) -> bool:
    return bool(user) and getattr(user, "type", None) == "admin"


def account_id_for(user):
    if user is None:
        return None
    if is_teams_mode():
        team_id = getattr(user, "team_id", None)
        return team_id  # None when the user has no team -> caller treats as unsolved
    return user.account_id


def has_solved(account_id, challenge_id) -> bool:
    if account_id is None:
        return False
    return (
        db.session.query(Solves.id)
        .filter(Solves.account_id == account_id, Solves.challenge_id == challenge_id)
        .first()
        is not None
    )


def ctf_ended() -> bool:
    return bool(ctfd_config.is_ctf_finished()) if hasattr(ctfd_config, "is_ctf_finished") else False


def challenge_exists(challenge_id) -> bool:
    return db.session.get(Challenges, challenge_id) is not None


def resolve_challenge_id(challenge_ref: str):
    ref = (challenge_ref or "").strip()
    if not ref:
        return None
    if ref.isdigit():
        cid = int(ref)
        return cid if challenge_exists(cid) else None
    rows = db.session.query(Challenges.id).filter(Challenges.name == ref).all()
    if len(rows) == 1:
        return rows[0][0]
    return None  # zero or ambiguous matches
```

> Verify in 3.7.6: `Solves.account_id` exists (it does in the account model era); `Users.account_id` exists; `is_ctf_finished` lives in `CTFd/utils/config/__init__.py`. If `ctf_ended` helper name differs, fix it here.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_compat.py -v`
Expected: PASS (4 tests). If `has_solved` fails on `account_id`, re-read `CTFd/models` for the solver-id column and adjust.

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/compat.py tests/test_compat.py
git commit -m "feat: CTFd 3.7.6 compatibility shim (solve check, mode, resolve)"
```

---

### Task 5: The solve gate

**Files:**
- Create: `ctfd_censored_writeups/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `compat.{current_user,is_admin,account_id_for,has_solved,ctf_ended}`, `config.get`.
- Produces:
  - `CENSORED = "censored"`, `UNCENSORED = "uncensored"`
  - `decide(app, user, challenge_id: int) -> str` — pure decision; takes `user` explicitly so it is unit-testable by injection.

- [ ] **Step 1: Write the failing tests (inject a fake compat via monkeypatch)**

`tests/test_gate.py`:
```python
import types
import ctfd_censored_writeups.gate as gate

class FakeUser:
    def __init__(self, admin=False): self.type = "admin" if admin else "user"

def _patch(monkeypatch, *, admin=False, solved=False, ended=False, open_after=False, account=7):
    monkeypatch.setattr(gate.compat, "is_admin", lambda u: admin)
    monkeypatch.setattr(gate.compat, "account_id_for", lambda u: account)
    monkeypatch.setattr(gate.compat, "has_solved", lambda a, c: solved)
    monkeypatch.setattr(gate.compat, "ctf_ended", lambda: ended)
    monkeypatch.setattr(gate, "_open_after_ctf", lambda app: open_after)

def test_unsolved_player_is_censored(monkeypatch):
    _patch(monkeypatch, solved=False)
    assert gate.decide(None, FakeUser(), 1) == gate.CENSORED

def test_solved_player_is_uncensored(monkeypatch):
    _patch(monkeypatch, solved=True)
    assert gate.decide(None, FakeUser(), 1) == gate.UNCENSORED

def test_admin_always_uncensored(monkeypatch):
    _patch(monkeypatch, admin=True, solved=False)
    assert gate.decide(None, FakeUser(admin=True), 1) == gate.UNCENSORED

def test_no_user_is_censored(monkeypatch):
    _patch(monkeypatch, solved=True)
    assert gate.decide(None, None, 1) == gate.CENSORED

def test_no_account_team_mode_is_censored(monkeypatch):
    _patch(monkeypatch, solved=False, account=None)
    assert gate.decide(None, FakeUser(), 1) == gate.CENSORED

def test_post_ctf_open_toggle_uncensors_all(monkeypatch):
    _patch(monkeypatch, solved=False, ended=True, open_after=True)
    assert gate.decide(None, FakeUser(), 1) == gate.UNCENSORED

def test_post_ctf_default_keeps_gate(monkeypatch):
    _patch(monkeypatch, solved=False, ended=True, open_after=False)
    assert gate.decide(None, FakeUser(), 1) == gate.CENSORED
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_gate.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the gate**

`ctfd_censored_writeups/gate.py`:
```python
from . import compat
from .config import get

CENSORED = "censored"
UNCENSORED = "uncensored"


def _open_after_ctf(app) -> bool:
    val = get(app, "WRITEUPS_OPEN_AFTER_CTF")
    return str(val).lower() in ("1", "true", "yes", "on") if not isinstance(val, bool) else val


def decide(app, user, challenge_id: int) -> str:
    if user is None:
        return CENSORED
    if compat.is_admin(user):
        return UNCENSORED
    if compat.ctf_ended() and _open_after_ctf(app):
        return UNCENSORED
    account_id = compat.account_id_for(user)
    if account_id is None:
        return CENSORED
    return UNCENSORED if compat.has_solved(account_id, challenge_id) else CENSORED
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_gate.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/gate.py tests/test_gate.py
git commit -m "feat: mode/admin/post-CTF-aware solve gate"
```

---

### Task 6: Sync engine

**Files:**
- Create: `ctfd_censored_writeups/sync.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `parser.parse_writeup_file`, `compat.resolve_challenge_id`, `models.{Writeup,WriteupUncensored}`.
- Produces:
  - `@dataclass SyncReport(created:int, updated:int, deleted:int, quarantined:int, errors:list[str])`
  - `sync_from_dir(app, repo_path: str) -> SyncReport` — walks `*.md` under `repo_path`, upserts by `source_key` (repo-relative path), deletes rows whose file vanished, quarantines rows that fail to parse or resolve. Idempotent.

- [ ] **Step 1: Write the failing tests**

`tests/test_sync.py`:
```python
import pathlib
from ctfd_censored_writeups.sync import sync_from_dir
from ctfd_censored_writeups.models import Writeup, WriteupUncensored

DOC = """---
challenge: {chal}
title: T
---
body <!--redact-->SECRET<!--/redact--> end
"""

def _write(repo, rel, text):
    p = pathlib.Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)

def test_sync_creates_rows_and_splits_binds(app, make_challenge, tmp_path):
    chal = make_challenge(name="rsa")
    repo = tmp_path / "repo"
    _write(repo, "crypto/rsa.md", DOC.format(chal=chal.id))
    with app.app_context():
        report = sync_from_dir(app, str(repo))
        assert report.created == 1
        w = Writeup.query.filter_by(source_key="crypto/rsa.md").one()
        assert w.challenge_id == chal.id
        assert "SECRET" not in w.censored_body
        u = WriteupUncensored.query.filter_by(writeup_id=w.id).one()
        assert "SECRET" in u.uncensored_body

def test_sync_is_idempotent(app, make_challenge, tmp_path):
    chal = make_challenge()
    repo = tmp_path / "repo"
    _write(repo, "a.md", DOC.format(chal=chal.id))
    with app.app_context():
        sync_from_dir(app, str(repo))
        report2 = sync_from_dir(app, str(repo))
        assert report2.created == 0 and report2.updated == 0
        assert Writeup.query.count() == 1

def test_sync_deletes_removed_files(app, make_challenge, tmp_path):
    chal = make_challenge()
    repo = tmp_path / "repo"
    f = repo / "a.md"
    _write(repo, "a.md", DOC.format(chal=chal.id))
    with app.app_context():
        sync_from_dir(app, str(repo))
    f.unlink()
    with app.app_context():
        report = sync_from_dir(app, str(repo))
        assert report.deleted == 1
        assert Writeup.query.count() == 0
        assert WriteupUncensored.query.count() == 0

def test_unresolved_challenge_is_quarantined(app, tmp_path):
    repo = tmp_path / "repo"
    _write(repo, "a.md", DOC.format(chal="DoesNotExist"))
    with app.app_context():
        report = sync_from_dir(app, str(repo))
        assert report.quarantined == 1
        w = Writeup.query.filter_by(source_key="a.md").one()
        assert w.quarantined is True
        assert w.challenge_id is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_sync.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the sync engine**

`ctfd_censored_writeups/sync.py`:
```python
import os
from dataclasses import dataclass, field
from CTFd.models import db
from .models import Writeup, WriteupUncensored
from .parser import parse_writeup_file
from . import compat


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    quarantined: int = 0
    errors: list = field(default_factory=list)


def _iter_markdown(repo_path):
    for root, _dirs, files in os.walk(repo_path):
        for name in files:
            if name.endswith(".md"):
                full = os.path.join(root, name)
                yield os.path.relpath(full, repo_path), full


def sync_from_dir(app, repo_path: str) -> SyncReport:
    report = SyncReport()
    seen = set()

    for source_key, full in _iter_markdown(repo_path):
        seen.add(source_key)
        try:
            text = open(full, encoding="utf-8").read()
        except OSError as e:
            report.errors.append(f"{source_key}: {e}")
            continue

        parsed = parse_writeup_file(text, source_key)
        challenge_id = compat.resolve_challenge_id(parsed.challenge_ref)
        quarantined = (not parsed.ok) or (challenge_id is None)

        w = Writeup.query.filter_by(source_key=source_key).first()
        is_new = w is None
        if is_new:
            w = Writeup(source_key=source_key)
            db.session.add(w)

        w.challenge_id = challenge_id
        w.title = parsed.title
        w.author = parsed.author
        w.censored_body = parsed.censored_body
        w.sort_order = parsed.sort_order
        w.tags = ",".join(parsed.tags) if parsed.tags else None
        w.language = parsed.language
        w.visible = parsed.visible
        w.quarantined = quarantined
        db.session.flush()  # assign w.id

        u = WriteupUncensored.query.filter_by(writeup_id=w.id).first()
        if u is None:
            u = WriteupUncensored(writeup_id=w.id)
            db.session.add(u)
        u.uncensored_body = parsed.uncensored_body

        if quarantined:
            report.quarantined += 1
        if is_new:
            report.created += 1
        # NOTE: "updated" counts only content changes; see Step 4 refinement.

    # Deletions: rows whose file disappeared.
    for w in Writeup.query.all():
        if w.source_key not in seen:
            WriteupUncensored.query.filter_by(writeup_id=w.id).delete()
            db.session.delete(w)
            report.deleted += 1

    db.session.commit()
    return report
```

- [ ] **Step 4: Refine `updated` accounting so idempotency test passes**

Replace the upsert body so unchanged rows are not counted as updated. Track a dirty flag:
```python
        # ... after building `parsed` and `challenge_id`, before mutating w:
        new_vals = dict(
            challenge_id=challenge_id, title=parsed.title, author=parsed.author,
            censored_body=parsed.censored_body, sort_order=parsed.sort_order,
            tags=",".join(parsed.tags) if parsed.tags else None,
            language=parsed.language, visible=parsed.visible, quarantined=quarantined,
        )
        changed = is_new or any(getattr(w, k) != v for k, v in new_vals.items())
        for k, v in new_vals.items():
            setattr(w, k, v)
        db.session.flush()
        u = WriteupUncensored.query.filter_by(writeup_id=w.id).first()
        if u is None:
            u = WriteupUncensored(writeup_id=w.id)
            db.session.add(u)
        if u.uncensored_body != parsed.uncensored_body:
            u.uncensored_body = parsed.uncensored_body
            changed = True
        if quarantined:
            report.quarantined += 1
        if is_new:
            report.created += 1
        elif changed:
            report.updated += 1
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_sync.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add ctfd_censored_writeups/sync.py tests/test_sync.py
git commit -m "feat: idempotent git-dir sync with quarantine and deletion"
```

---

### Task 7: CLI sync command

**Files:**
- Modify: `ctfd_censored_writeups/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `sync.sync_from_dir`, `config.get`.
- Produces: a Flask CLI group `writeups` with `sync` subcommand that pulls the git repo (if `repo_path` is a git working copy) then runs `sync_from_dir`. Registered via `cli.register(app)`.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
import pathlib

def test_cli_sync_runs(app, make_challenge, tmp_path):
    chal = make_challenge()
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "a.md").write_text(f"---\nchallenge: {chal.id}\ntitle: T\n---\nbody")
    import os
    os.environ["WRITEUPS_REPO_PATH"] = str(repo)
    runner = app.test_cli_runner()
    result = runner.invoke(args=["writeups", "sync"])
    assert result.exit_code == 0
    assert "created=1" in result.output
    from ctfd_censored_writeups.models import Writeup
    with app.app_context():
        assert Writeup.query.count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL (no `writeups` command).

- [ ] **Step 3: Implement the CLI**

`ctfd_censored_writeups/cli.py`:
```python
import os
import click
from flask.cli import AppGroup
from .config import get
from .sync import sync_from_dir


def register(app):
    writeups_cli = AppGroup("writeups", help="Censored-writeups plugin commands.")

    @writeups_cli.command("sync")
    def sync_cmd():
        """Pull the writeups repo (if a git checkout) and sync into the DB."""
        repo_path = get(app, "WRITEUPS_REPO_PATH")
        _git_pull_if_present(repo_path)
        with app.app_context():
            report = sync_from_dir(app, repo_path)
        click.echo(
            f"created={report.created} updated={report.updated} "
            f"deleted={report.deleted} quarantined={report.quarantined} "
            f"errors={len(report.errors)}"
        )

    app.cli.add_command(writeups_cli)


def _git_pull_if_present(repo_path):
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return
    try:
        from git import Repo
        Repo(repo_path).remotes.origin.pull()
    except Exception as e:  # pragma: no cover - network/seed edge
        click.echo(f"git pull skipped: {e}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/cli.py tests/test_cli.py
git commit -m "feat: flask writeups sync CLI command"
```

---

### Task 8: Single-writeup route (gated, IDOR-safe)

**Files:**
- Modify: `ctfd_censored_writeups/views.py`
- Create: `ctfd_censored_writeups/templates/writeup_single.html`
- Test: `tests/test_routes_single.py`

**Interfaces:**
- Consumes: `gate.decide`, `compat.current_user`, `models.{Writeup,WriteupUncensored}`, CTFd `authed_only`, CTFd `markdown`.
- Produces: `GET /writeups/<int:challenge_id>/<int:writeup_id>` — renders one writeup. **Challenge association comes from the row, never the URL.** Adds `Cache-Control: private, no-store`.

- [ ] **Step 1: Write the failing tests**

`tests/test_routes_single.py`:
```python
import pathlib
from ctfd_censored_writeups.sync import sync_from_dir

DOC = "---\nchallenge: {c}\ntitle: T\n---\nintro <!--redact-->FLAG{{secret}}<!--/redact--> outro\n"

def _seed(app, tmp_path, challenge_id):
    repo = tmp_path / "repo"; (repo).mkdir(exist_ok=True)
    (repo / "a.md").write_text(DOC.format(c=challenge_id))
    with app.app_context():
        sync_from_dir(app, str(repo))
        from ctfd_censored_writeups.models import Writeup
        return Writeup.query.filter_by(source_key="a.md").one().id

def test_unsolved_sees_censored(app, make_user, make_challenge, tmp_path):
    from CTFd.tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}/{wid}")
    assert r.status_code == 200
    assert b"FLAG{secret}" not in r.data
    assert r.headers["Cache-Control"] == "private, no-store"

def test_solved_sees_uncensored(app, make_user, make_challenge, make_solve, tmp_path):
    from CTFd.tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}/{wid}")
    assert b"FLAG{secret}" in r.data

def test_idor_uses_row_challenge_not_url(app, make_user, make_challenge, make_solve, tmp_path):
    # Writeup belongs to challenge A; user solved only B; URL lies with B's id.
    from CTFd.tests.helpers import login_as_user
    a = make_challenge(name="A"); b = make_challenge(name="B"); u = make_user()
    wid = _seed(app, tmp_path, a.id)
    make_solve(user_id=u.id, challenge_id=b.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{b.id}/{wid}")   # attacker passes solved B's id
    assert b"FLAG{secret}" not in r.data         # still censored: row says A
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_routes_single.py -v`
Expected: FAIL (route missing).

- [ ] **Step 3: Implement the route + template**

`ctfd_censored_writeups/views.py`:
```python
from flask import render_template, abort
from CTFd.utils.decorators import authed_only
from CTFd.utils import markdown
from .models import Writeup, WriteupUncensored
from . import compat, gate
from flask import current_app


def _render_body(writeup):
    user = compat.current_user()
    # IDOR discipline: association comes from the stored row, not the URL.
    decision = gate.decide(current_app, user, writeup.challenge_id)
    if decision == gate.UNCENSORED and writeup.challenge_id is not None:
        body = WriteupUncensored.query.filter_by(writeup_id=writeup.id).one().uncensored_body
        unlocked = True
    else:
        body = writeup.censored_body
        unlocked = False
    return markdown(body), unlocked


def register(blueprint):
    @blueprint.route("/writeups/<int:challenge_id>/<int:writeup_id>")
    @authed_only
    def single(challenge_id, writeup_id):
        w = Writeup.query.filter_by(id=writeup_id).first()
        if w is None or w.quarantined or not w.visible:
            abort(404)
        html, unlocked = _render_body(w)
        resp = current_app.make_response(
            render_template("writeup_single.html", writeup=w, body_html=html, unlocked=unlocked)
        )
        resp.headers["Cache-Control"] = "private, no-store"
        return resp
```

`ctfd_censored_writeups/templates/writeup_single.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container writeup-single">
  <h2>{{ writeup.title }}</h2>
  {% if writeup.author %}<p class="text-muted">by {{ writeup.author }}</p>{% endif %}
  <span class="badge {{ 'badge-success' if unlocked else 'badge-secondary' }}">
    {{ 'Unlocked' if unlocked else 'Censored — solve to unlock' }}
  </span>
  <hr>
  <div class="writeup-body">{{ body_html | safe }}</div>
</div>
{% endblock %}
```

> Verify `base.html` is the correct theme base in 3.7.6 (`grep -rn "{% extends" $PKG/themes/core-beta/templates` or the active theme). If the core theme base differs, use the self-contained layout from Task 10 instead of extending the theme.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_routes_single.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/views.py ctfd_censored_writeups/templates/writeup_single.html tests/test_routes_single.py
git commit -m "feat: gated, IDOR-safe single-writeup route"
```

---

### Task 9: List route + JSON API

**Files:**
- Modify: `ctfd_censored_writeups/views.py`
- Create: `ctfd_censored_writeups/templates/writeups_list.html`
- Test: `tests/test_routes_list_api.py`

**Interfaces:**
- Consumes: same as Task 8.
- Produces:
  - `GET /writeups/<int:challenge_id>` — list of visible, non-quarantined writeups for the challenge (title, author, tags, sort_order, per-entry `unlocked` badge). The list is not secret; bodies are not included.
  - `GET /api/v1/writeups/<int:challenge_id>` — JSON list (same metadata, no bodies).
  - `GET /api/v1/writeups/<int:challenge_id>/<int:writeup_id>` — JSON single; `body` is censored unless the gate (run against the row's challenge) returns UNCENSORED. `Cache-Control: private, no-store`.

- [ ] **Step 1: Write the failing tests**

`tests/test_routes_list_api.py`:
```python
from tests.test_routes_single import _seed   # reuse seeding helper

def test_list_shows_metadata_not_body(app, make_user, make_challenge, tmp_path):
    from CTFd.tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/writeups/{c.id}")
    assert r.status_code == 200
    assert b"T" in r.data                 # title present
    assert b"FLAG{secret}" not in r.data  # no body content

def test_api_single_unsolved_is_censored(app, make_user, make_challenge, tmp_path):
    from CTFd.tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}/{wid}")
    data = r.get_json()
    assert "FLAG{secret}" not in data["body"]
    assert r.headers["Cache-Control"] == "private, no-store"

def test_api_single_solved_is_uncensored(app, make_user, make_challenge, make_solve, tmp_path):
    from CTFd.tests.helpers import login_as_user
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get(f"/api/v1/writeups/{c.id}/{wid}")
    assert "FLAG{secret}" in r.get_json()["body"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_routes_list_api.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement list + API routes**

Add to `register(blueprint)` in `views.py`:
```python
    from flask import jsonify

    def _visible_for(challenge_id):
        return (
            Writeup.query.filter_by(challenge_id=challenge_id, visible=True, quarantined=False)
            .order_by(Writeup.sort_order.asc(), Writeup.id.asc())
            .all()
        )

    def _entry_meta(w):
        user = compat.current_user()
        unlocked = gate.decide(current_app, user, w.challenge_id) == gate.UNCENSORED
        return {
            "id": w.id, "challenge_id": w.challenge_id, "title": w.title,
            "author": w.author, "tags": w.tags.split(",") if w.tags else [],
            "sort_order": w.sort_order, "unlocked": unlocked,
        }

    @blueprint.route("/writeups/<int:challenge_id>")
    @authed_only
    def listing(challenge_id):
        items = [_entry_meta(w) for w in _visible_for(challenge_id)]
        resp = current_app.make_response(
            render_template("writeups_list.html", challenge_id=challenge_id, items=items)
        )
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @blueprint.route("/api/v1/writeups/<int:challenge_id>")
    @authed_only
    def api_list(challenge_id):
        resp = jsonify({"success": True, "data": [_entry_meta(w) for w in _visible_for(challenge_id)]})
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @blueprint.route("/api/v1/writeups/<int:challenge_id>/<int:writeup_id>")
    @authed_only
    def api_single(challenge_id, writeup_id):
        w = Writeup.query.filter_by(id=writeup_id).first()
        if w is None or w.quarantined or not w.visible:
            abort(404)
        html, unlocked = _render_body(w)
        resp = jsonify({"success": True, "data": {
            "id": w.id, "title": w.title, "unlocked": unlocked, "body": html,
        }})
        resp.headers["Cache-Control"] = "private, no-store"
        return resp
```

`ctfd_censored_writeups/templates/writeups_list.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container">
  <h2>Writeups</h2>
  {% if not items %}<p>No writeups for this challenge yet.</p>{% endif %}
  <ul class="list-group">
    {% for it in items %}
    <li class="list-group-item d-flex justify-content-between">
      <a href="/writeups/{{ it.challenge_id }}/{{ it.id }}">{{ it.title }}</a>
      <span>
        {% if it.author %}<small class="text-muted">{{ it.author }}</small>{% endif %}
        <span class="badge {{ 'badge-success' if it.unlocked else 'badge-secondary' }}">
          {{ 'Unlocked' if it.unlocked else 'Censored' }}
        </span>
      </span>
    </li>
    {% endfor %}
  </ul>
</div>
{% endblock %}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_routes_list_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/views.py ctfd_censored_writeups/templates/writeups_list.html tests/test_routes_list_api.py
git commit -m "feat: writeup list page and gated JSON API"
```

---

### Task 10: Self-contained browsing UI + nav link

**Files:**
- Create: `ctfd_censored_writeups/assets/writeups.css`, `ctfd_censored_writeups/assets/writeups.js`
- Modify: `ctfd_censored_writeups/__init__.py` (register assets + nav), `templates/writeups_list.html` (mount point)
- Test: `tests/test_routes_list_api.py` (extend)

**Interfaces:**
- Consumes: the JSON API from Task 9.
- Produces: a two-pane reader (index list + reading pane) driven client-side against the API; a nav-bar link "Writeups". Self-contained so it survives theme upgrades.

- [ ] **Step 1: Write the failing test (asset + nav registration)**

Add to `tests/test_routes_list_api.py`:
```python
def test_assets_served(app):
    client = app.test_client()
    r = client.get("/plugins/ctfd_censored_writeups/assets/writeups.js")
    assert r.status_code == 200

def test_nav_link_registered(app):
    # The plugin registered a user-facing menu entry pointing at /writeups.
    from CTFd.utils.plugins import get_registered_user_page_menu_bar  # verify name in 3.7.6
    with app.app_context():
        hrefs = [m.route if hasattr(m, "route") else m.get("route") for m in get_registered_user_page_menu_bar()]
    assert any("/writeups" in (h or "") for h in hrefs)
```

> Verify the menu accessor name in 3.7.6 (`grep -rn "menu_bar" $PKG/utils/plugins/__init__.py $PKG/plugins/__init__.py`). If it differs, fix the import in the test and the registration call together.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_routes_list_api.py -v -k "assets or nav"`
Expected: FAIL.

- [ ] **Step 3: Register assets + nav in `load`**

Add to `__init__.py` `load(app)` after `app.register_blueprint(blueprint)`:
```python
    from CTFd.plugins import register_plugin_assets_directory, register_user_page_menu_bar
    register_plugin_assets_directory(app, base_path="/plugins/ctfd_censored_writeups/assets/")
    register_user_page_menu_bar("Writeups", "/writeups")
```

> If the writeups landing needs a challenge id, point the nav at a small index page `/writeups` that lists challenges having writeups; add that route in `views.py` mirroring `listing` but grouping by `challenge_id`. Keep it `@authed_only`.

- [ ] **Step 4: Implement the client UI**

`ctfd_censored_writeups/assets/writeups.css`:
```css
.wu-wrap { display: flex; gap: 1rem; }
.wu-index { width: 16rem; border-right: 1px solid #ddd; }
.wu-read { flex: 1; }
.wu-badge { font-size: 0.75rem; }
```

`ctfd_censored_writeups/assets/writeups.js`:
```javascript
// Minimal, dependency-free reader. Reads challenge id from data attribute.
async function loadList(challengeId) {
  const res = await fetch(`/api/v1/writeups/${challengeId}`, { credentials: "same-origin" });
  const { data } = await res.json();
  const idx = document.getElementById("wu-index");
  idx.innerHTML = "";
  data.forEach((it) => {
    const a = document.createElement("a");
    a.href = "#"; a.textContent = it.title;
    a.onclick = (e) => { e.preventDefault(); loadOne(it.challenge_id, it.id); };
    idx.appendChild(a); idx.appendChild(document.createElement("br"));
  });
  if (data.length) loadOne(data[0].challenge_id, data[0].id);
}
async function loadOne(challengeId, writeupId) {
  const res = await fetch(`/api/v1/writeups/${challengeId}/${writeupId}`, { credentials: "same-origin" });
  const { data } = await res.json();
  document.getElementById("wu-read").innerHTML = data.body; // server already gated+rendered
}
window.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("wu-root");
  if (root) loadList(root.dataset.challengeId);
});
```

Add the mount point to `writeups_list.html` (keep the server-rendered `<ul>` as no-JS fallback):
```html
<div id="wu-root" data-challenge-id="{{ challenge_id }}" class="wu-wrap">
  <div id="wu-index" class="wu-index"></div>
  <div id="wu-read" class="wu-read"></div>
</div>
<script src="/plugins/ctfd_censored_writeups/assets/writeups.js"></script>
<link rel="stylesheet" href="/plugins/ctfd_censored_writeups/assets/writeups.css">
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_routes_list_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ctfd_censored_writeups/assets ctfd_censored_writeups/__init__.py ctfd_censored_writeups/templates/writeups_list.html tests/test_routes_list_api.py
git commit -m "feat: self-contained writeup browser UI + nav link"
```

---

### Task 11: Webhook + admin sync page

**Files:**
- Modify: `ctfd_censored_writeups/views.py`, `ctfd_censored_writeups/__init__.py`
- Create: `ctfd_censored_writeups/templates/admin_writeups.html`
- Test: `tests/test_webhook.py`

**Interfaces:**
- Consumes: `sync.sync_from_dir`, `config.get`, CTFd `admins_only`.
- Produces:
  - `POST /writeups/_webhook` — verifies `X-Hub-Signature-256: sha256=<hmac>` over the raw body using `WRITEUPS_WEBHOOK_SECRET`; on success pulls + syncs; 401 on bad/missing signature; 503 if secret unset.
  - `GET /admin/writeups` (`@admins_only`) — status + "Sync now" button (POST to an admin sync route).

- [ ] **Step 1: Write the failing tests**

`tests/test_webhook.py`:
```python
import hashlib, hmac, os, pathlib

def _sig(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

def test_webhook_rejects_bad_signature(app, tmp_path):
    os.environ["WRITEUPS_WEBHOOK_SECRET"] = "s3cret"
    client = app.test_client()
    r = client.post("/writeups/_webhook", data=b"{}", headers={"X-Hub-Signature-256": "sha256=bad"})
    assert r.status_code == 401

def test_webhook_accepts_good_signature(app, make_challenge, tmp_path):
    secret = "s3cret"; os.environ["WRITEUPS_WEBHOOK_SECRET"] = secret
    chal = make_challenge()
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "a.md").write_text(f"---\nchallenge: {chal.id}\ntitle: T\n---\nbody")
    os.environ["WRITEUPS_REPO_PATH"] = str(repo)
    body = b"{}"
    client = app.test_client()
    r = client.post("/writeups/_webhook", data=body,
                    headers={"X-Hub-Signature-256": _sig(secret, body)})
    assert r.status_code == 200
    from ctfd_censored_writeups.models import Writeup
    with app.app_context():
        assert Writeup.query.count() == 1

def test_admin_page_requires_admin(app, make_user):
    from CTFd.tests.helpers import login_as_user
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/admin/writeups")
    assert r.status_code in (302, 403)  # non-admin redirected/forbidden
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_webhook.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement webhook + admin routes**

Add to `register(blueprint)` in `views.py`:
```python
    import hmac, hashlib
    from flask import request
    from CTFd.utils.decorators import admins_only
    from .config import get as cfg_get
    from .sync import sync_from_dir
    from .cli import _git_pull_if_present

    @blueprint.route("/writeups/_webhook", methods=["POST"])
    def webhook():
        secret = cfg_get(current_app, "WRITEUPS_WEBHOOK_SECRET")
        if not secret:
            abort(503)
        sent = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), request.get_data(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sent, expected):
            abort(401)
        repo_path = cfg_get(current_app, "WRITEUPS_REPO_PATH")
        _git_pull_if_present(repo_path)
        report = sync_from_dir(current_app, repo_path)
        return {"success": True, "created": report.created, "updated": report.updated,
                "deleted": report.deleted, "quarantined": report.quarantined}

    @blueprint.route("/admin/writeups", methods=["GET"])
    @admins_only
    def admin_page():
        total = Writeup.query.count()
        quarantined = Writeup.query.filter_by(quarantined=True).count()
        return render_template("admin_writeups.html", total=total, quarantined=quarantined)

    @blueprint.route("/admin/writeups/sync", methods=["POST"])
    @admins_only
    def admin_sync():
        repo_path = cfg_get(current_app, "WRITEUPS_REPO_PATH")
        _git_pull_if_present(repo_path)
        report = sync_from_dir(current_app, repo_path)
        return {"success": True, "created": report.created, "updated": report.updated,
                "deleted": report.deleted, "quarantined": report.quarantined}
```

`ctfd_censored_writeups/templates/admin_writeups.html`:
```html
{% extends "admin/base.html" %}
{% block content %}
<div class="container">
  <h2>Writeups</h2>
  <p>Total: {{ total }} — Quarantined: {{ quarantined }}</p>
  <button id="wu-sync" class="btn btn-primary">Sync now</button>
  <pre id="wu-sync-out"></pre>
  <script>
    document.getElementById("wu-sync").onclick = async () => {
      const r = await fetch("/admin/writeups/sync", {method: "POST", headers: {"CSRF-Token": init.csrfNonce}});
      document.getElementById("wu-sync-out").textContent = await r.text();
    };
  </script>
</div>
{% endblock %}
```

> Verify `admin/base.html` and the CSRF nonce accessor (`init.csrfNonce`) in 3.7.6's admin theme. If CSRF handling differs, follow the pattern other admin POSTs in the theme use.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_webhook.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/views.py ctfd_censored_writeups/templates/admin_writeups.html tests/test_webhook.py
git commit -m "feat: HMAC-verified webhook and admin sync page"
```

---

### Task 12: The leak/gate matrix (the invariant, end-to-end)

**Files:**
- Test: `tests/test_leak_matrix.py`

**Interfaces:**
- Consumes: all routes. Adds no production code unless a hole is found — then fix in the offending module.

- [ ] **Step 1: Write the matrix test**

`tests/test_leak_matrix.py`:
```python
import itertools, pathlib
from ctfd_censored_writeups.sync import sync_from_dir
from CTFd.tests.helpers import login_as_user

SECRET = "FLAG{do_not_leak}"
DOC = f"---\nchallenge: {{c}}\ntitle: T\n---\nintro <!--redact-->{SECRET}<!--/redact--> ```flag\nsolve.py\n``` outro\n"

def _seed(app, tmp_path, cid):
    repo = tmp_path / "repo"; repo.mkdir(exist_ok=True)
    (repo / "a.md").write_text(DOC.format(c=cid))
    with app.app_context():
        sync_from_dir(app, str(repo))
        from ctfd_censored_writeups.models import Writeup
        return Writeup.query.filter_by(source_key="a.md").one().id

def _assert_no_secret(resp):
    assert SECRET.encode() not in resp.data
    assert b"solve.py" not in resp.data

def test_unsolved_player_never_sees_secret_anywhere(app, make_user, make_challenge, tmp_path):
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    client = login_as_user(app, name=u.name, password="pw")
    for url in (f"/writeups/{c.id}", f"/writeups/{c.id}/{wid}",
                f"/api/v1/writeups/{c.id}", f"/api/v1/writeups/{c.id}/{wid}",
                f"/writeups/{c.id}/999999"):  # 404 path
        _assert_no_secret(client.get(url))

def test_solved_player_sees_secret(app, make_user, make_challenge, make_solve, tmp_path):
    c = make_challenge(); u = make_user()
    wid = _seed(app, tmp_path, c.id)
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert SECRET.encode() in client.get(f"/writeups/{c.id}/{wid}").data

def test_idor_cross_challenge_no_leak(app, make_user, make_challenge, make_solve, tmp_path):
    a = make_challenge(name="A"); b = make_challenge(name="B"); u = make_user()
    wid = _seed(app, tmp_path, a.id)
    make_solve(user_id=u.id, challenge_id=b.id)
    client = login_as_user(app, name=u.name, password="pw")
    _assert_no_secret(client.get(f"/writeups/{b.id}/{wid}"))
```

- [ ] **Step 2: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS. If any leak test fails, the invariant is broken — fix the responsible module (do NOT weaken the test), re-run, then commit.

- [ ] **Step 3: Commit**

```bash
git add tests/test_leak_matrix.py
git commit -m "test: end-to-end leak/IDOR invariant across all routes"
```

---

### Task 13: Documentation deliverable

**Files:**
- Create: `ctfd_censored_writeups/docs/writeup-format.md`, `ctfd_censored_writeups/docs/how-it-works.md`, `ctfd_censored_writeups/docs/operator-setup.md`, `README.md`
- Modify: `ctfd_censored_writeups/templates/admin_writeups.html` (link to docs)

**Interfaces:** none (documentation). This task closes the spec's §8 deliverable.

- [ ] **Step 1: Write `writeup-format.md`**

Document, with a complete example file: the frontmatter schema (`challenge`, `title`, `author`, `sort_order`, `tags`, `language`, `visible` — required/optional/defaults), the `challenge:` id-then-name resolution rule, redaction marker syntax (inline `<!--redact-->...<!--/redact-->` and fenced ```` ```flag ````/```` ```spoiler ````), the fail-closed behavior (unclosed/nested markers redact to end and quarantine), and how the repo-relative file path is the stable `source_key` (renaming a file = delete + create).

- [ ] **Step 2: Write `how-it-works.md`**

Document the solve gate (user vs team mode, teammate unlock, admin preview bypass, post-CTF toggle), the two-bind storage model and what isolation it buys, the sync flow (webhook → pull → upsert; plus manual button and `flask writeups sync`), quarantine behavior (bad/missing frontmatter, unresolved/ambiguous challenge, orphaned challenge), and the leakage invariant authors must respect.

- [ ] **Step 3: Write `operator-setup.md`**

Document: installing the plugin into `CTFd/plugins/`, setting `WRITEUPS_UNCENSORED_BIND_URI` (and why it should be a separate file/credential), `WRITEUPS_REPO_PATH`, generating and setting `WRITEUPS_WEBHOOK_SECRET` and wiring the git provider webhook to `POST /writeups/_webhook` with `X-Hub-Signature-256`, the `WRITEUPS_OPEN_AFTER_CTF` toggle, and running the initial seed via `flask writeups sync`.

- [ ] **Step 4: Write `README.md`**

One-screen overview: what the plugin does, the invariant, links to the three docs and to the design spec.

- [ ] **Step 5: Link docs from the admin page**

Add to `admin_writeups.html`:
```html
<p><a href="https://github.com/your-org/CTFd_writeup_plugin/blob/main/ctfd_censored_writeups/docs/operator-setup.md" target="_blank">Setup &amp; format docs</a></p>
```

- [ ] **Step 6: Commit**

```bash
git add ctfd_censored_writeups/docs README.md ctfd_censored_writeups/templates/admin_writeups.html
git commit -m "docs: writeup format, how-it-works, operator setup"
```

---

## Self-Review

**Spec coverage:**
- §0 invariant → Tasks 8/9/12 (gate in routes, leak matrix). ✓
- §1 git-markdown source / read-mostly → Tasks 6/7/11. ✓
- §1 derived censoring → Tasks 2/3. ✓
- §1 defense-in-depth two binds → Tasks 0/1 (bind registered, models split); unsolved path never queries `WriteupUncensored` (Task 8 `_render_body` only opens it on UNCENSORED). ✓
- §1 target 3.7.6 / compat shim → Tasks 0/4. ✓
- §1 post-CTF toggle → Task 5 + config. ✓
- §1 self-contained UI + nav → Task 10. ✓
- §1 webhook + manual + CLI → Tasks 7/11. ✓
- §1 challenge id-then-name mapping → Task 4 `resolve_challenge_id`. ✓
- §8 documentation → Task 13. ✓
- §5 IDOR discipline → Tasks 8/12. ✓
- §6 cache headers, fail-closed, redaction verify, flag scan → Tasks 8/9 (headers), 2 (fail-closed + verify). NOTE: the optional flag-in-censored scan (§6 belt-and-suspenders) is NOT yet a task — see addition below.
- §10 gate matrix testing → Tasks 5/12. ✓

**Gap found:** §6's optional "scan censored body for the challenge's flag" is unimplemented. It is explicitly optional in the spec, but cheap. Add it as a quarantine condition in sync:

> **Task 6 addendum (fold into Task 6 before its commit):** after computing `parsed`, if `challenge_id` resolved, fetch the challenge's static flags (`from CTFd.models import Flags; Flags.query.filter_by(challenge_id=challenge_id, type="static")`) and if any flag string appears in `parsed.censored_body`, set `quarantined = True` and append an error. Add a test `test_flag_in_censored_is_quarantined` mirroring `test_unresolved_challenge_is_quarantined`. Dynamic/regex flags are not scanned (documented limitation in `how-it-works.md`).

**Placeholder scan:** no TBD/TODO/"handle errors" placeholders; every code step shows complete code. ✓

**Type consistency:** `CensorResult`, `ParsedWriteup`, `SyncReport`, `decide(app,user,challenge_id)`, `resolve_challenge_id(str)->int|None`, `_render_body(writeup)->(html,unlocked)` are referenced consistently across tasks. ✓

---

## Execution Notes

- Run the full suite (`.venv/bin/pytest -v`) at the end of every task, not just the task's own file — the leak invariant is global.
- The three places that touch CTFd version internals (`compat.py`, the `base.html`/`admin/base.html` template extends, the nav/asset registration calls) each carry a "verify against 3.7.6 source" instruction. Do that verification rather than trusting the snippet.
