# Writeup Submission System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let solvers submit writeups from the plugin's /writeups pages into a moderation queue; admins review/edit/grade and approve or reject; approved writeups publish into the existing `Writeup`/`WriteupUncensored` tables under a `submission://<id>` source-key namespace; Discord webhooks announce submissions and decisions.

**Architecture:** One new table `WriteupSubmission` in the **uncensored bind** (raw bodies are presumed to contain flags). A new `publish.py` module composes a canonical frontmatter document and funnels it through the existing `parse_writeup_file` → redaction → static-flag-scan pipeline, so submissions and file sync share one fail-closed path. `sync_from_dir` learns to leave the `submission://` namespace alone. New route modules `submissions.py` (player-facing) and `admin_review.py` (admin queue/review) register on the existing blueprint. `notify.py` fires best-effort Discord webhooks.

**Tech Stack:** CTFd 3.7.6 plugin (Flask, SQLAlchemy two-bind), server-rendered plain-HTML templates (existing plugin style), pytest with the existing `tests/conftest.py` fixtures.

**Spec:** `docs/superpowers/specs/2026-07-19-writeup-submission-design.md`

## Global Constraints

- `WriteupSubmission` lives in the uncensored bind: `__bind_key__ = "uncensored"`. Raw submission bodies must never be written to the main DB.
- Published submission source keys are exactly `submission://<id>` (constant `SUBMISSION_PREFIX = "submission://"`).
- One live submission per (user_id, challenge_id), enforced by a unique constraint.
- Only solvers may submit; POST re-validates eligibility server-side (never trust the dropdown).
- Body size cap: 1 MiB (`MAX_BODY_BYTES = 1_048_576`), measured on UTF-8 bytes.
- Approval is **blocked** (HTTP 400, reasons shown) while the body fails to parse, has malformed redaction markers, or leaks a static flag into the censored output — never publish quarantined content from this path.
- Discord webhook payloads never contain writeup bodies or admin comments — titles, challenge names, author, score only. Delivery failures are logged and swallowed.
- Statuses are exactly the strings `pending`, `approved`, `rejected`.
- All POST forms carry CTFd's CSRF nonce as a hidden `nonce` field (from `flask.session["nonce"]`); fetch calls send the `CSRF-Token` header.
- `llm_report` is reserved: rendered read-only when non-null; nothing writes it in this project.
- New CTFd-internal lookups go in `compat.py` only (the single module allowed to touch CTFd internals).
- Run tests with `pytest tests/<file> -v` from the repo root.

---

### Task 1: `WriteupSubmission` model

**Files:**
- Modify: `ctfd_censored_writeups/models.py`
- Test: `tests/test_submission_model.py` (create)

**Interfaces:**
- Consumes: `CTFd.models.db`, existing model file patterns.
- Produces: `WriteupSubmission` model and status constants `STATUS_PENDING = "pending"`, `STATUS_APPROVED = "approved"`, `STATUS_REJECTED = "rejected"` importable from `ctfd_censored_writeups.models`. Columns: `id, challenge_id, user_id, account_id, title, author, body_raw, body_edited, status, admin_comment, score, reviewed_by, reviewed_at, llm_report, writeup_id, created_at, updated_at`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_submission_model.py`:

```python
def test_submission_roundtrip_and_defaults(app):
    from ctfd_censored_writeups.models import WriteupSubmission, STATUS_PENDING
    with app.app_context():
        s = WriteupSubmission(challenge_id=1, user_id=2, account_id=2,
                              title="T", author="alice", body_raw="FLAG{x} body")
        app.db.session.add(s)
        app.db.session.commit()
        got = WriteupSubmission.query.one()
        assert got.status == STATUS_PENDING
        assert got.body_edited is None
        assert got.score is None
        assert got.llm_report is None
        assert got.writeup_id is None
        assert got.created_at is not None
        assert got.updated_at is not None


def test_submission_lives_in_uncensored_bind_only(app):
    """Raw bodies are presumed to contain flags: the table must exist in the
    uncensored bind and must NOT exist in the main DB."""
    import sqlalchemy
    from ctfd_censored_writeups.models import WriteupSubmission  # noqa: F401
    with app.app_context():
        main = sqlalchemy.inspect(app.db.get_engine(app))
        unc = sqlalchemy.inspect(app.db.get_engine(app, bind="uncensored"))
        assert "plugin_writeup_submissions" not in main.get_table_names()
        assert "plugin_writeup_submissions" in unc.get_table_names()


def test_one_live_submission_per_user_and_challenge(app):
    import pytest, sqlalchemy
    from ctfd_censored_writeups.models import WriteupSubmission
    with app.app_context():
        app.db.session.add(WriteupSubmission(challenge_id=1, user_id=2, account_id=2,
                                             title="a", author="a", body_raw="a"))
        app.db.session.commit()
        app.db.session.add(WriteupSubmission(challenge_id=1, user_id=2, account_id=2,
                                             title="b", author="b", body_raw="b"))
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            app.db.session.commit()
        app.db.session.rollback()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_submission_model.py -v`
Expected: FAIL/ERROR with `ImportError: cannot import name 'WriteupSubmission'`

- [ ] **Step 3: Implement the model**

Append to `ctfd_censored_writeups/models.py`:

```python
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class WriteupSubmission(db.Model):
    """Player-submitted writeup awaiting review. Lives in the uncensored bind:
    an unreviewed body is presumed to contain flags, and the main DB must
    never hold secrets."""
    __bind_key__ = "uncensored"
    __tablename__ = "plugin_writeup_submissions"

    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    account_id = db.Column(db.Integer, nullable=False)
    title = db.Column(db.Text, nullable=False)
    author = db.Column(db.Text, nullable=False)
    body_raw = db.Column(db.Text, nullable=False)
    body_edited = db.Column(db.Text, nullable=True)   # admin-edited; published body is body_edited or body_raw
    status = db.Column(db.String(16), nullable=False, default=STATUS_PENDING, index=True)
    admin_comment = db.Column(db.Text, nullable=True)
    score = db.Column(db.Integer, nullable=True)      # internal grade, admin-only
    reviewed_by = db.Column(db.Integer, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    llm_report = db.Column(db.Text, nullable=True)    # reserved for LLM pre-review JSON
    writeup_id = db.Column(db.Integer, nullable=True)  # published Writeup row (no cross-bind FK by design)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("user_id", "challenge_id", name="uq_submission_user_challenge"),
    )
```

(`datetime`/`timezone` are already imported at the top of `models.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_submission_model.py -v`
Expected: 3 PASS

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add ctfd_censored_writeups/models.py tests/test_submission_model.py
git commit -m "feat: WriteupSubmission model in the uncensored bind"
```

---

### Task 2: `publish.py` — compose, evaluate, shared flag-leak check

**Files:**
- Create: `ctfd_censored_writeups/publish.py`
- Modify: `ctfd_censored_writeups/sync.py:44-58` (use the shared leak helper)
- Test: `tests/test_publish.py` (create)

**Interfaces:**
- Consumes: `parse_writeup_file(text, source_key) -> ParsedWriteup` (fields used: `ok`, `censored_body`, `uncensored_body`, `title`, `author`), `compat.static_flag_values(challenge_id) -> list[str]`.
- Produces:
  - `SUBMISSION_PREFIX = "submission://"`
  - `source_key_for(sub_id: int) -> str` — returns `f"submission://{sub_id}"`
  - `compose_document(challenge_id: int, title: str, author: str | None, body: str) -> str`
  - `censored_body_leaks_flag(challenge_id, censored_body) -> bool`
  - `Evaluation` dataclass with `parsed: ParsedWriteup` and `warnings: list[str]`
  - `evaluate(challenge_id: int, body: str) -> Evaluation`
  - Warning strings: `WARN_MALFORMED = "redaction markers are malformed (fail-closed)"`, `WARN_FLAG_LEAK = "censored body still contains a static flag"`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_publish.py`:

```python
def test_compose_document_roundtrips_through_parser(app):
    from ctfd_censored_writeups.publish import compose_document
    from ctfd_censored_writeups.parser import parse_writeup_file
    doc = compose_document(42, "My Title", "alice", "hello <!--redact-->FLAG{x}<!--/redact--> world")
    p = parse_writeup_file(doc, "submission://1")
    assert p.ok
    assert p.challenge_ref == "42"          # numeric -> resolved as ID, never ambiguous
    assert p.title == "My Title"
    assert p.author == "alice"
    assert "FLAG{x}" not in p.censored_body
    assert "FLAG{x}" in p.uncensored_body


def test_compose_document_handles_tricky_yaml_title(app):
    from ctfd_censored_writeups.publish import compose_document
    from ctfd_censored_writeups.parser import parse_writeup_file
    doc = compose_document(7, 'Quote " and : colon', None, "body")
    p = parse_writeup_file(doc, "k")
    assert p.ok
    assert p.title == 'Quote " and : colon'
    assert p.author is None


def test_evaluate_clean_body_has_no_warnings(app, make_challenge):
    from ctfd_censored_writeups.publish import evaluate
    c = make_challenge()
    with app.app_context():
        ev = evaluate(c.id, "safe <!--redact-->FLAG{x}<!--/redact--> text")
        assert ev.warnings == []
        assert "FLAG{x}" not in ev.parsed.censored_body


def test_evaluate_flags_malformed_redaction(app, make_challenge):
    from ctfd_censored_writeups.publish import evaluate, WARN_MALFORMED
    c = make_challenge()
    with app.app_context():
        ev = evaluate(c.id, "oops <!--redact-->never closed")
        assert WARN_MALFORMED in ev.warnings


def test_evaluate_flags_static_flag_leak(app, make_challenge):
    from tests.helpers import gen_flag
    from ctfd_censored_writeups.publish import evaluate, WARN_FLAG_LEAK
    c = make_challenge()
    with app.app_context():
        gen_flag(app.db, challenge_id=c.id, content="CTF{leaky}")
        ev = evaluate(c.id, "the flag is CTF{leaky}, whoops")
        assert WARN_FLAG_LEAK in ev.warnings


def test_source_key_namespace(app):
    from ctfd_censored_writeups.publish import source_key_for, SUBMISSION_PREFIX
    assert source_key_for(9) == "submission://9"
    assert source_key_for(9).startswith(SUBMISSION_PREFIX)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_publish.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'ctfd_censored_writeups.publish'`

- [ ] **Step 3: Implement `publish.py` (part 1)**

Create `ctfd_censored_writeups/publish.py`:

```python
"""
Publish pipeline for player submissions.

A submission is composed into a canonical frontmatter document and pushed
through the SAME parse -> redaction -> flag-scan path as file sync, so there
is exactly one fail-closed pipeline to audit. Published rows use the
`submission://<id>` source-key namespace, which file paths can never collide
with; sync's deletion pass skips that namespace.
"""
from dataclasses import dataclass, field

import yaml

from .parser import parse_writeup_file, ParsedWriteup
from . import compat

SUBMISSION_PREFIX = "submission://"

WARN_MALFORMED = "redaction markers are malformed (fail-closed)"
WARN_FLAG_LEAK = "censored body still contains a static flag"


def source_key_for(sub_id: int) -> str:
    return f"{SUBMISSION_PREFIX}{sub_id}"


def compose_document(challenge_id: int, title: str, author: str | None, body: str) -> str:
    # challenge as a digit-string resolves by ID (never ambiguous-name quarantine).
    fm = {"challenge": str(challenge_id), "title": title}
    if author:
        fm["author"] = author
    fm_text = yaml.safe_dump(fm, default_flow_style=False, allow_unicode=True)
    return f"---\n{fm_text}---\n\n{body}"


def censored_body_leaks_flag(challenge_id, censored_body) -> bool:
    """Shared with sync: does any static flag appear verbatim in the censored
    output? Dynamic/regex flags are NOT detected (same limitation as sync)."""
    if challenge_id is None or not censored_body:
        return False
    for flag_val in compat.static_flag_values(challenge_id):
        if flag_val and flag_val in censored_body:
            return True
    return False


@dataclass
class Evaluation:
    parsed: ParsedWriteup
    warnings: list = field(default_factory=list)


def evaluate(challenge_id: int, body: str) -> Evaluation:
    """Run a submission body through the real pipeline and report blockers.

    Title/author don't affect redaction, so a placeholder title is used; the
    real publish re-parses with the submission's actual fields.
    """
    doc = compose_document(challenge_id, "preview", None, body)
    parsed = parse_writeup_file(doc, "submission://preview")
    warnings = []
    if not parsed.ok:
        warnings.append(WARN_MALFORMED)
    if censored_body_leaks_flag(challenge_id, parsed.censored_body):
        warnings.append(WARN_FLAG_LEAK)
    return Evaluation(parsed=parsed, warnings=warnings)
```

- [ ] **Step 4: Refactor `sync.py` to use the shared leak helper (behavior-neutral)**

In `ctfd_censored_writeups/sync.py`, replace the flag-scan block (lines 46–58, the comment plus the `flag_leaked = False` loop) with:

```python
            # Flag scan: check whether any static flag value appears verbatim in
            # the censored body. This catches authors accidentally leaving the
            # flag outside a <!--redact-->…<!--/redact--> block.
            # NOTE: dynamic/regex flags are NOT detected; only static flag content
            # strings that appear as a literal substring are caught here.
            flag_leaked = False
            if parsed.ok and censored_body_leaks_flag(challenge_id, parsed.censored_body):
                flag_leaked = True
                report.errors.append(
                    f"{source_key}: censored body contains the challenge's static flag (redacted)"
                )
```

and add to the imports at the top of `sync.py`:

```python
from .publish import censored_body_leaks_flag
```

(`censored_body_leaks_flag` already handles `challenge_id is None` and empty bodies, so the old `challenge_id is not None and parsed.censored_body` guards are preserved.)

- [ ] **Step 5: Run tests to verify they pass, including existing sync tests**

Run: `pytest tests/test_publish.py tests/test_sync.py -v`
Expected: all PASS (sync behavior unchanged)

- [ ] **Step 6: Commit**

```bash
git add ctfd_censored_writeups/publish.py ctfd_censored_writeups/sync.py tests/test_publish.py
git commit -m "feat: publish pipeline (compose/evaluate) sharing sync's flag scan"
```

---

### Task 3: publish/unpublish + sync namespace guard

**Files:**
- Modify: `ctfd_censored_writeups/publish.py` (append functions)
- Modify: `ctfd_censored_writeups/sync.py:109-114` (deletion pass)
- Test: `tests/test_publish.py` (append)

**Interfaces:**
- Consumes: `WriteupSubmission` (Task 1), `Writeup`, `WriteupUncensored`, `source_key_for`, `compose_document` (Task 2).
- Produces:
  - `publish_submission(sub) -> Writeup` — upserts `Writeup` + `WriteupUncensored` for `source_key_for(sub.id)`, flushes (caller commits). Caller must have verified `evaluate(...)` returned no warnings.
  - `unpublish_submission(sub) -> None` — deletes both rows if present (caller commits).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_publish.py`:

```python
def _make_submission(app, challenge_id, body="b <!--redact-->FLAG{x}<!--/redact--> a",
                     user_id=2, title="T", author="alice"):
    from ctfd_censored_writeups.models import WriteupSubmission
    with app.app_context():
        s = WriteupSubmission(challenge_id=challenge_id, user_id=user_id,
                              account_id=user_id, title=title, author=author,
                              body_raw=body)
        app.db.session.add(s)
        app.db.session.commit()
        sid = s.id
    return sid


def test_publish_submission_upserts_both_binds(app, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission, Writeup, WriteupUncensored
    from ctfd_censored_writeups.publish import publish_submission
    c = make_challenge()
    sid = _make_submission(app, c.id)
    with app.app_context():
        sub = app.db.session.get(WriteupSubmission, sid)
        w = publish_submission(sub)
        app.db.session.commit()
        got = Writeup.query.filter_by(source_key=f"submission://{sid}").one()
        assert got.id == w.id
        assert got.challenge_id == c.id
        assert got.title == "T"
        assert got.author == "alice"
        assert got.visible is True
        assert got.quarantined is False
        assert "FLAG{x}" not in got.censored_body
        u = WriteupUncensored.query.filter_by(writeup_id=got.id).one()
        assert "FLAG{x}" in u.uncensored_body


def test_publish_submission_uses_edited_body_when_present(app, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission, Writeup, WriteupUncensored
    from ctfd_censored_writeups.publish import publish_submission
    c = make_challenge()
    sid = _make_submission(app, c.id, body="original")
    with app.app_context():
        sub = app.db.session.get(WriteupSubmission, sid)
        sub.body_edited = "edited by admin"
        w = publish_submission(sub)
        app.db.session.commit()
        assert "edited by admin" in WriteupUncensored.query.filter_by(writeup_id=w.id).one().uncensored_body


def test_republish_is_idempotent_upsert(app, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission, Writeup
    from ctfd_censored_writeups.publish import publish_submission
    c = make_challenge()
    sid = _make_submission(app, c.id)
    with app.app_context():
        sub = app.db.session.get(WriteupSubmission, sid)
        first = publish_submission(sub).id
        app.db.session.commit()
        sub = app.db.session.get(WriteupSubmission, sid)
        sub.title = "T2"
        again = publish_submission(sub).id
        app.db.session.commit()
        assert first == again
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").count() == 1
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").one().title == "T2"


def test_unpublish_removes_both_rows(app, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission, Writeup, WriteupUncensored
    from ctfd_censored_writeups.publish import publish_submission, unpublish_submission
    c = make_challenge()
    sid = _make_submission(app, c.id)
    with app.app_context():
        sub = app.db.session.get(WriteupSubmission, sid)
        w = publish_submission(sub)
        app.db.session.commit()
        wid = w.id
        unpublish_submission(sub)
        app.db.session.commit()
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is None
        assert WriteupUncensored.query.filter_by(writeup_id=wid).first() is None


def test_sync_leaves_submission_namespace_alone(app, make_challenge, tmp_path):
    """THE critical regression test for the one change to existing code: a full
    sync run must not delete published submissions (their source_key is not a
    file on disk)."""
    from ctfd_censored_writeups.models import WriteupSubmission, Writeup
    from ctfd_censored_writeups.publish import publish_submission
    from ctfd_censored_writeups.sync import sync_from_dir
    c = make_challenge()
    sid = _make_submission(app, c.id)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "a.md").write_text(f"---\nchallenge: {c.id}\ntitle: F\n---\nfile body\n")
    with app.app_context():
        sub = app.db.session.get(WriteupSubmission, sid)
        publish_submission(sub)
        app.db.session.commit()
        report = sync_from_dir(app, str(repo))
        assert report.deleted == 0
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is not None
        assert Writeup.query.filter_by(source_key="a.md").first() is not None
        # and the reverse: deleting the FILE still works
        (repo / "a.md").unlink()
        report = sync_from_dir(app, str(repo))
        assert report.deleted == 1
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_publish.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'publish_submission'`

- [ ] **Step 3: Implement publish/unpublish**

Append to `ctfd_censored_writeups/publish.py`:

```python
def publish_submission(sub):
    """Upsert Writeup + WriteupUncensored for an approved submission.

    Caller must have verified evaluate(...) returned no warnings, and commits.
    Returns the Writeup row (flushed, id assigned).
    """
    from CTFd.models import db
    from .models import Writeup, WriteupUncensored

    body = sub.body_edited or sub.body_raw
    key = source_key_for(sub.id)
    parsed = parse_writeup_file(compose_document(sub.challenge_id, sub.title, sub.author, body), key)

    w = Writeup.query.filter_by(source_key=key).first()
    if w is None:
        w = Writeup(source_key=key)
        db.session.add(w)
    w.challenge_id = sub.challenge_id
    w.title = sub.title
    w.author = sub.author
    w.censored_body = parsed.censored_body
    w.sort_order = 0
    w.tags = None
    w.language = None
    w.visible = True
    w.quarantined = False
    db.session.flush()  # assign w.id if new

    u = WriteupUncensored.query.filter_by(writeup_id=w.id).first()
    if u is None:
        u = WriteupUncensored(writeup_id=w.id)
        db.session.add(u)
    u.uncensored_body = parsed.uncensored_body
    return w


def unpublish_submission(sub):
    """Delete the published rows for a submission, if any. Caller commits."""
    from CTFd.models import db
    from .models import Writeup, WriteupUncensored

    w = Writeup.query.filter_by(source_key=source_key_for(sub.id)).first()
    if w is not None:
        WriteupUncensored.query.filter_by(writeup_id=w.id).delete()
        db.session.delete(w)
```

- [ ] **Step 4: Guard the sync deletion pass**

In `ctfd_censored_writeups/sync.py`, replace the deletion pass:

```python
    # Deletion pass: rows whose file no longer exists are removed from both binds.
    for w in Writeup.query.all():
        if w.source_key not in seen:
            WriteupUncensored.query.filter_by(writeup_id=w.id).delete()
            db.session.delete(w)
            report.deleted += 1
```

with:

```python
    # Deletion pass: rows whose file no longer exists are removed from both
    # binds. Rows in the submission:// namespace are owned by the review flow,
    # not by files on disk — sync must never touch them.
    for w in Writeup.query.all():
        if w.source_key.startswith(SUBMISSION_PREFIX):
            continue
        if w.source_key not in seen:
            WriteupUncensored.query.filter_by(writeup_id=w.id).delete()
            db.session.delete(w)
            report.deleted += 1
```

and extend the existing publish import in `sync.py`:

```python
from .publish import censored_body_leaks_flag, SUBMISSION_PREFIX
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_publish.py tests/test_sync.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add ctfd_censored_writeups/publish.py ctfd_censored_writeups/sync.py tests/test_publish.py
git commit -m "feat: publish/unpublish submissions; sync skips submission:// namespace"
```

---

### Task 4: Discord notifications (`notify.py`)

**Files:**
- Create: `ctfd_censored_writeups/notify.py`
- Modify: `ctfd_censored_writeups/config.py:4-9` (add key to `DEFAULTS`)
- Test: `tests/test_notify.py` (create)

**Interfaces:**
- Consumes: `config.get(app, key)`.
- Produces:
  - `DEFAULTS["WRITEUPS_DISCORD_WEBHOOK_URL"] = ""` (empty = feature off)
  - `notify_submitted(app, title, challenge_name, author) -> None`
  - `notify_reviewed(app, title, challenge_name, approved: bool, score=None) -> None`
  - Both are best-effort: no-op when unconfigured; failures logged and swallowed; 5-second timeout; payload is `{"content": <message>}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notify.py`:

```python
import pytest


@pytest.fixture
def capture_posts(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})

    from ctfd_censored_writeups import notify
    monkeypatch.setattr(notify.requests, "post", fake_post)
    return calls


def test_noop_when_unconfigured(app, capture_posts, monkeypatch):
    from ctfd_censored_writeups import notify
    monkeypatch.delenv("WRITEUPS_DISCORD_WEBHOOK_URL", raising=False)
    notify.notify_submitted(app, "T", "chal", "alice")
    assert capture_posts == []


def test_submitted_message(app, capture_posts, monkeypatch):
    from ctfd_censored_writeups import notify
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    notify.notify_submitted(app, "My Writeup", "Web 101", "alice")
    assert len(capture_posts) == 1
    c = capture_posts[0]
    assert c["url"] == "https://discord.test/hook"
    assert c["timeout"] == 5
    msg = c["json"]["content"]
    assert "My Writeup" in msg and "Web 101" in msg and "alice" in msg
    assert "pending review" in msg


def test_reviewed_messages(app, capture_posts, monkeypatch):
    from ctfd_censored_writeups import notify
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    notify.notify_reviewed(app, "T", "Web 101", approved=True, score=8)
    notify.notify_reviewed(app, "T", "Web 101", approved=False)
    approved_msg = capture_posts[0]["json"]["content"]
    rejected_msg = capture_posts[1]["json"]["content"]
    assert "Approved" in approved_msg and "8" in approved_msg
    assert "Rejected" in rejected_msg


def test_failure_is_swallowed(app, monkeypatch):
    from ctfd_censored_writeups import notify

    def boom(url, json=None, timeout=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(notify.requests, "post", boom)
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    notify.notify_submitted(app, "T", "chal", "a")  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_notify.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'ctfd_censored_writeups.notify'`

- [ ] **Step 3: Implement `notify.py` and the config key**

Create `ctfd_censored_writeups/notify.py`:

```python
"""
Best-effort Discord webhook announcements. Payloads never contain writeup
bodies or admin comments (the channel may be semi-public; bodies may contain
flags) — titles, challenge names, author, and score only. A dead webhook must
never break a submission or a review: failures are logged and swallowed.
"""
import requests

from .config import get

TIMEOUT_SECONDS = 5


def _post(app, content: str):
    url = get(app, "WRITEUPS_DISCORD_WEBHOOK_URL")
    if not url:
        return
    try:
        requests.post(url, json={"content": content}, timeout=TIMEOUT_SECONDS)
    except Exception:
        app.logger.warning("writeups: discord webhook delivery failed", exc_info=True)


def notify_submitted(app, title, challenge_name, author):
    _post(app, f"\U0001F4DD New writeup pending review: *{title}* for *{challenge_name}* by {author}")


def notify_reviewed(app, title, challenge_name, approved: bool, score=None):
    if approved:
        msg = f"✅ Approved: *{title}* for *{challenge_name}*"
        if score is not None:
            msg += f" — score: {score}"
    else:
        msg = f"❌ Rejected: *{title}* for *{challenge_name}*"
    _post(app, msg)
```

In `ctfd_censored_writeups/config.py`, add to `DEFAULTS`:

```python
    "WRITEUPS_DISCORD_WEBHOOK_URL": "",             # Discord announcements; empty disables
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notify.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/notify.py ctfd_censored_writeups/config.py tests/test_notify.py
git commit -m "feat: best-effort Discord webhook notifications"
```

---

### Task 5: `compat` helpers — solved challenges, names

**Files:**
- Modify: `ctfd_censored_writeups/compat.py` (append)
- Test: `tests/test_compat.py` (append)

**Interfaces:**
- Consumes: `CTFd.models` (`db`, `Solves`, `Challenges`, `Users`), `is_teams_mode`.
- Produces:
  - `solved_challenges(account_id) -> list[tuple[int, str]]` — (id, name) of challenges solved by the account, name-sorted; `[]` for `None`.
  - `challenge_name(challenge_id) -> str | None`
  - `user_name(user_id) -> str | None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_compat.py`:

```python
def test_solved_challenges_lists_only_solved_sorted(app, make_user, make_challenge, make_solve):
    from ctfd_censored_writeups import compat
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
    from ctfd_censored_writeups import compat
    with app.app_context():
        assert compat.solved_challenges(None) == []


def test_challenge_and_user_name_lookups(app, make_user, make_challenge):
    from ctfd_censored_writeups import compat
    c = make_challenge(name="Named")
    u = make_user()
    with app.app_context():
        assert compat.challenge_name(c.id) == "Named"
        assert compat.challenge_name(99999) is None
        assert compat.user_name(u.id) == u.name
        assert compat.user_name(99999) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_compat.py -v`
Expected: new tests FAIL with `AttributeError: ... has no attribute 'solved_challenges'`

- [ ] **Step 3: Implement the helpers**

Append to `ctfd_censored_writeups/compat.py`:

```python
def solved_challenges(account_id):
    """(id, name) of challenges solved by the account, name-sorted.

    Same mode-aware column choice as has_solved: Solves.team_id in team mode,
    Solves.user_id in user mode (Solves.account_id has no SQL expression).
    """
    if account_id is None:
        return []
    col = Solves.team_id if is_teams_mode() else Solves.user_id
    rows = (
        db.session.query(Challenges.id, Challenges.name)
        .join(Solves, Solves.challenge_id == Challenges.id)
        .filter(col == account_id)
        .order_by(Challenges.name.asc())
        .all()
    )
    return [(r[0], r[1]) for r in rows]


def challenge_name(challenge_id):
    row = db.session.query(Challenges.name).filter(Challenges.id == challenge_id).first()
    return row[0] if row else None


def user_name(user_id):
    from CTFd.models import Users
    u = db.session.get(Users, user_id)
    return u.name if u else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_compat.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/compat.py tests/test_compat.py
git commit -m "feat: compat helpers for solved challenges and name lookups"
```

---

### Task 6: Submit form — GET + POST routes

**Files:**
- Create: `ctfd_censored_writeups/submissions.py`
- Create: `ctfd_censored_writeups/templates/submit_writeup.html`
- Modify: `ctfd_censored_writeups/__init__.py:19-21` (wire `submissions.register`)
- Test: `tests/test_submit_routes.py` (create)

**Interfaces:**
- Consumes: `WriteupSubmission` + status constants (Task 1), `notify.notify_submitted` (Task 4), `compat.solved_challenges`/`challenge_name` (Task 5), `compat.has_solved`/`account_id_for`/`challenge_exists`/`challenge_is_visible`.
- Produces: `submissions.register(blueprint)` adding routes `GET /writeups/submit`, `POST /writeups/submit` (and, in Task 7, `GET /writeups/mine`). `MAX_BODY_BYTES = 1_048_576`. POST redirects to `/writeups/mine` on success.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_submit_routes.py`:

```python
def _nonce(client):
    with client.session_transaction() as sess:
        return sess.get("nonce")


def _submit(client, challenge_id, title="T", body="hello world", author=""):
    return client.post("/writeups/submit", data={
        "nonce": _nonce(client), "challenge_id": challenge_id,
        "title": title, "author": author, "body": body,
    })


def test_form_lists_only_solved_challenges(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    solved = make_challenge(name="Solved One")
    unsolved = make_challenge(name="Not Solved")
    u = make_user()
    make_solve(user_id=u.id, challenge_id=solved.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/writeups/submit")
    assert r.status_code == 200
    assert b"Solved One" in r.data
    assert b"Not Solved" not in r.data


def test_form_without_solves_shows_note(app, make_user, make_challenge):
    from tests.helpers import login_as_user
    make_challenge()
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/writeups/submit")
    assert r.status_code == 200
    assert b"solve" in r.data.lower()


def test_solver_can_submit(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = _submit(client, c.id, body="I solved it like this")
    assert r.status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission
        s = WriteupSubmission.query.one()
        assert s.challenge_id == c.id
        assert s.user_id == u.id
        assert s.status == "pending"
        assert s.author == u.name  # empty author falls back to display name
        assert s.body_raw == "I solved it like this"


def test_non_solver_gets_403_even_with_forged_id(app, make_user, make_challenge):
    """IDOR discipline: the dropdown only shows solved challenges, but the POST
    must re-check server-side."""
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = _submit(client, c.id)
    assert r.status_code == 403
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission
        assert WriteupSubmission.query.count() == 0


def test_unknown_challenge_404(app, make_user):
    from tests.helpers import login_as_user
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, 99999).status_code == 404


def test_hidden_challenge_403(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge(state="hidden")
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id).status_code == 403


def test_empty_title_or_body_400(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id, title="  ").status_code == 400
    assert _submit(client, c.id, body="  ").status_code == 400


def test_body_size_cap_413(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id, body="x" * (1_048_576 + 1)).status_code == 413


def test_resubmit_overwrites_and_resets(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id, title="v1", body="first").status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, STATUS_REJECTED
        s = WriteupSubmission.query.one()
        s.status = STATUS_REJECTED
        s.admin_comment = "too short"
        s.score = 2
        s.body_edited = "admin tweak"
        s.llm_report = '{"verdict": "stale"}'
        app.db.session.commit()
    assert _submit(client, c.id, title="v2", body="second, longer").status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission
        s = WriteupSubmission.query.one()  # still exactly one row
        assert s.title == "v2"
        assert s.body_raw == "second, longer"
        assert s.status == "pending"
        assert s.admin_comment is None
        assert s.score is None
        assert s.body_edited is None
        assert s.llm_report is None


def test_cannot_overwrite_approved_submission(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id).status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, STATUS_APPROVED
        s = WriteupSubmission.query.one()
        s.status = STATUS_APPROVED
        app.db.session.commit()
    assert _submit(client, c.id, title="try again").status_code == 409


def test_submit_fires_webhook_without_body_text(app, make_user, make_challenge, make_solve, monkeypatch):
    from tests.helpers import login_as_user
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json)

    from ctfd_censored_writeups import notify
    monkeypatch.setattr(notify.requests, "post", fake_post)
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    c = make_challenge(name="Webby")
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    r = _submit(client, c.id, title="Hook Title", body="SECRETBODY FLAG{x}")
    assert r.status_code == 302
    assert len(calls) == 1
    msg = calls[0]["content"]
    assert "Hook Title" in msg and "Webby" in msg
    assert "SECRETBODY" not in msg and "FLAG{x}" not in msg


def test_webhook_failure_does_not_break_submit(app, make_user, make_challenge, make_solve, monkeypatch):
    from tests.helpers import login_as_user

    def boom(url, json=None, timeout=None):
        raise RuntimeError("down")

    from ctfd_censored_writeups import notify
    monkeypatch.setattr(notify.requests, "post", boom)
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    c = make_challenge()
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id).status_code == 302
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_submit_routes.py -v`
Expected: FAIL — `GET /writeups/submit` returns 404 (route doesn't exist)

- [ ] **Step 3: Implement routes and template**

Create `ctfd_censored_writeups/submissions.py`:

```python
"""
Player-facing submission routes: the submit form and (Task 7) "my submissions".

Eligibility is enforced server-side on POST regardless of what the dropdown
showed: the challenge must exist, be visible, and be solved by the account.
"""
from flask import abort, current_app, redirect, render_template, request, session
from CTFd.models import db
from CTFd.utils.decorators import authed_only

from .models import WriteupSubmission, STATUS_PENDING, STATUS_APPROVED
from . import compat, notify

MAX_BODY_BYTES = 1_048_576  # 1 MiB; images are URLs, so text never hits this


def _choices_for(user):
    """(id, name) of solved challenges without an approved submission yet."""
    solved = compat.solved_challenges(compat.account_id_for(user))
    approved = {
        s.challenge_id
        for s in WriteupSubmission.query.filter_by(user_id=user.id, status=STATUS_APPROVED)
    }
    return [(cid, name) for cid, name in solved if cid not in approved]


def register(blueprint):
    @blueprint.route("/writeups/submit", methods=["GET"])
    @authed_only
    def submit_form():
        user = compat.current_user()
        choices = _choices_for(user)
        selected_id = request.args.get("challenge_id", type=int)
        prefill = None
        if selected_id:
            prefill = (
                WriteupSubmission.query
                .filter_by(user_id=user.id, challenge_id=selected_id)
                .filter(WriteupSubmission.status != STATUS_APPROVED)
                .first()
            )
        return render_template(
            "submit_writeup.html",
            choices=choices, prefill=prefill, selected_id=selected_id,
            default_author=user.name, nonce=session.get("nonce"),
        )

    @blueprint.route("/writeups/submit", methods=["POST"])
    @authed_only
    def submit_post():
        user = compat.current_user()
        account_id = compat.account_id_for(user)
        challenge_id = request.form.get("challenge_id", type=int)
        title = (request.form.get("title") or "").strip()
        author = (request.form.get("author") or "").strip() or user.name
        body = request.form.get("body") or ""

        if not challenge_id or not compat.challenge_exists(challenge_id):
            abort(404)
        if not compat.challenge_is_visible(challenge_id):
            abort(403)
        if not compat.has_solved(account_id, challenge_id):
            abort(403)
        if not title or not body.strip():
            abort(400)
        if len(body.encode("utf-8")) > MAX_BODY_BYTES:
            abort(413)

        sub = WriteupSubmission.query.filter_by(
            user_id=user.id, challenge_id=challenge_id
        ).first()
        if sub is not None and sub.status == STATUS_APPROVED:
            abort(409, description="already published — contact an admin")
        if sub is None:
            sub = WriteupSubmission(user_id=user.id, challenge_id=challenge_id,
                                    account_id=account_id)
            db.session.add(sub)
        sub.title = title
        sub.author = author
        sub.body_raw = body
        # Resubmission resets the review state entirely.
        sub.status = STATUS_PENDING
        sub.body_edited = None
        sub.admin_comment = None
        sub.score = None
        sub.reviewed_by = None
        sub.reviewed_at = None
        sub.llm_report = None
        db.session.commit()

        notify.notify_submitted(
            current_app, title,
            compat.challenge_name(challenge_id) or f"#{challenge_id}", author,
        )
        return redirect("/writeups/mine")
```

Create `ctfd_censored_writeups/templates/submit_writeup.html`:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Submit a Writeup</title>
</head>
<body>
<div class="container">
  <h2>Submit a Writeup</h2>
  {% if not choices %}
  <p>You need to solve a challenge before you can submit a writeup for it.</p>
  {% else %}
  <form method="POST" action="/writeups/submit">
    <input type="hidden" name="nonce" value="{{ nonce }}">
    <p>
      <label for="wu-challenge">Challenge</label><br>
      <select name="challenge_id" id="wu-challenge" required>
        {% for cid, cname in choices %}
        <option value="{{ cid }}" {% if cid == selected_id %}selected{% endif %}>{{ cname }}</option>
        {% endfor %}
      </select>
    </p>
    <p>
      <label for="wu-title">Title</label><br>
      <input type="text" name="title" id="wu-title" size="60" required
             value="{{ prefill.title if prefill else '' }}">
    </p>
    <p>
      <label for="wu-author">Author (shown publicly)</label><br>
      <input type="text" name="author" id="wu-author" size="60"
             value="{{ prefill.author if prefill else default_author }}">
    </p>
    <p>
      <label for="wu-file">Load body from a .md file (optional)</label><br>
      <input type="file" id="wu-file" accept=".md,text/markdown,text/plain">
    </p>
    <p>
      <textarea name="body" id="wu-body" rows="20" cols="90" required>{{ prefill.body_raw if prefill else '' }}</textarea>
    </p>
    <p>
      Mark flags and spoilers with <code>&lt;!--redact--&gt;…&lt;!--/redact--&gt;</code>
      or fenced <code>```flag</code> / <code>```spoiler</code> blocks — see the
      <a href="https://github.com/your-org/CTFd_writeup_plugin/blob/main/ctfd_censored_writeups/docs/writeup-format.md"
         target="_blank">format docs</a>.<br>
      Host images externally (imgur, GitHub, &hellip;) and reference them by URL;
      do not embed base64 images. Images cannot be redacted — never screenshot the flag.
    </p>
    <button type="submit" class="btn btn-primary">Submit for review</button>
  </form>
  <script>
    document.getElementById("wu-file").addEventListener("change", function (e) {
      var f = e.target.files[0];
      if (!f) return;
      var reader = new FileReader();
      reader.onload = function () { document.getElementById("wu-body").value = reader.result; };
      reader.readAsText(f);
    });
  </script>
  {% endif %}
</div>
</body>
</html>
```

In `ctfd_censored_writeups/__init__.py`, after `views.register(blueprint)` add:

```python
    from . import submissions
    submissions.register(blueprint)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_submit_routes.py -v`
Expected: all PASS except the two that hit `/writeups/mine` after redirect — the redirect itself (302) is asserted, so all tests in this file PASS. (`/writeups/mine` is Task 7; nothing here follows the redirect.)

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add ctfd_censored_writeups/submissions.py ctfd_censored_writeups/templates/submit_writeup.html ctfd_censored_writeups/__init__.py tests/test_submit_routes.py
git commit -m "feat: solver-gated writeup submission form"
```

---

### Task 7: "My submissions" page + index entry points

**Files:**
- Modify: `ctfd_censored_writeups/submissions.py` (append route)
- Create: `ctfd_censored_writeups/templates/my_submissions.html`
- Modify: `ctfd_censored_writeups/templates/writeups_index.html`
- Test: `tests/test_submit_routes.py` (append)

**Interfaces:**
- Consumes: `WriteupSubmission`, `compat.challenge_name`.
- Produces: `GET /writeups/mine` (own submissions only); "Submit a writeup" / "My submissions" links on `/writeups`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_submit_routes.py`:

```python
def test_mine_shows_own_submissions_with_status_and_comment(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge(name="Mine Chal")
    u = make_user()
    make_solve(user_id=u.id, challenge_id=c.id)
    client = login_as_user(app, name=u.name, password="pw")
    assert _submit(client, c.id, title="Mine Title").status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, STATUS_REJECTED
        s = WriteupSubmission.query.one()
        s.status = STATUS_REJECTED
        s.admin_comment = "needs more detail"
        s.score = 3
        app.db.session.commit()
    r = client.get("/writeups/mine")
    assert r.status_code == 200
    assert b"Mine Title" in r.data
    assert b"Mine Chal" in r.data
    assert b"rejected" in r.data
    assert b"needs more detail" in r.data
    assert b">3<" not in r.data  # score is internal, never shown to submitters


def test_mine_does_not_show_other_users_submissions(app, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    u1 = make_user(name="alice", email="a@x.io")
    u2 = make_user(name="bob", email="b@x.io")
    make_solve(user_id=u1.id, challenge_id=c.id)
    client1 = login_as_user(app, name="alice", password="pw")
    assert _submit(client1, c.id, title="AliceOnly").status_code == 302
    client2 = login_as_user(app, name="bob", password="pw")
    r = client2.get("/writeups/mine")
    assert r.status_code == 200
    assert b"AliceOnly" not in r.data


def test_index_links_to_submit_and_mine(app, make_user):
    from tests.helpers import login_as_user
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/writeups")
    assert b"/writeups/submit" in r.data
    assert b"/writeups/mine" in r.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_submit_routes.py -v`
Expected: new tests FAIL — `/writeups/mine` returns 404, index lacks links

- [ ] **Step 3: Implement**

Append inside `register(blueprint)` in `ctfd_censored_writeups/submissions.py`:

```python
    @blueprint.route("/writeups/mine")
    @authed_only
    def my_submissions():
        user = compat.current_user()
        subs = (
            WriteupSubmission.query.filter_by(user_id=user.id)
            .order_by(WriteupSubmission.updated_at.desc())
            .all()
        )
        names = {s.challenge_id: compat.challenge_name(s.challenge_id) for s in subs}
        return render_template("my_submissions.html", subs=subs, names=names)
```

Create `ctfd_censored_writeups/templates/my_submissions.html`:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>My Writeup Submissions</title>
</head>
<body>
<div class="container">
  <h2>My Writeup Submissions</h2>
  <p><a href="/writeups/submit">Submit a writeup</a> &middot; <a href="/writeups">All writeups</a></p>
  {% if not subs %}<p>No submissions yet.</p>{% endif %}
  <table class="table">
    {% if subs %}
    <tr><th>Challenge</th><th>Title</th><th>Status</th><th>Reviewer comment</th><th></th></tr>
    {% endif %}
    {% for s in subs %}
    <tr>
      <td>{{ names[s.challenge_id] or ("#" ~ s.challenge_id) }}</td>
      <td>{{ s.title }}</td>
      <td>{{ s.status }}</td>
      <td>{% if s.status == "rejected" %}{{ s.admin_comment or "" }}{% endif %}</td>
      <td>
        {% if s.status == "approved" and s.writeup_id %}
        <a href="/writeups/{{ s.challenge_id }}/{{ s.writeup_id }}">view</a>
        {% else %}
        <a href="/writeups/submit?challenge_id={{ s.challenge_id }}">edit &amp; resubmit</a>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>
</div>
</body>
</html>
```

In `ctfd_censored_writeups/templates/writeups_index.html`, after `<h2>Writeups</h2>` insert:

```html
  <p>
    <a href="/writeups/submit">Submit a writeup</a> &middot;
    <a href="/writeups/mine">My submissions</a>
  </p>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_submit_routes.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/submissions.py ctfd_censored_writeups/templates/my_submissions.html ctfd_censored_writeups/templates/writeups_index.html tests/test_submit_routes.py
git commit -m "feat: my-submissions page and index entry points"
```

---

### Task 8: Admin queue on the writeups admin page

**Files:**
- Modify: `ctfd_censored_writeups/views.py:150-155` (`admin_page`)
- Modify: `ctfd_censored_writeups/templates/admin_writeups.html`
- Test: `tests/test_admin_review.py` (create)

**Interfaces:**
- Consumes: `WriteupSubmission`, `compat.challenge_name`, `compat.user_name`.
- Produces: `GET /admin/writeups?status=pending|approved|rejected|all` (default `pending`) renders the submission queue; each row links to `/admin/writeups/submissions/<id>` (page implemented in Task 9).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_review.py`:

```python
def _nonce(client):
    with client.session_transaction() as sess:
        return sess.get("nonce")


def _seed_submission(app, challenge_id, user_id, title="Queue Title",
                     body="b <!--redact-->FLAG{x}<!--/redact--> a", status="pending"):
    from ctfd_censored_writeups.models import WriteupSubmission
    with app.app_context():
        s = WriteupSubmission(challenge_id=challenge_id, user_id=user_id,
                              account_id=user_id, title=title, author="alice",
                              body_raw=body, status=status)
        app.db.session.add(s)
        app.db.session.commit()
        return s.id


def _admin_client(app, make_admin):
    from tests.helpers import login_as_user
    make_admin()
    return login_as_user(app, name="testadmin", password="pw")


def test_queue_defaults_to_pending(app, make_admin, make_user, make_challenge):
    c = make_challenge(name="Queue Chal")
    u = make_user()
    _seed_submission(app, c.id, u.id, title="PendingOne", status="pending")
    _seed_submission_id2 = _seed_submission(app, c.id, u.id + 1000, title="DoneOne", status="approved")
    client = _admin_client(app, make_admin)
    r = client.get("/admin/writeups")
    assert r.status_code == 200
    assert b"PendingOne" in r.data
    assert b"Queue Chal" in r.data
    assert b"DoneOne" not in r.data


def test_queue_status_filters(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    _seed_submission(app, c.id, u.id, title="PendingOne", status="pending")
    _seed_submission(app, c.id, u.id + 1000, title="ApprovedOne", status="approved")
    client = _admin_client(app, make_admin)
    r = client.get("/admin/writeups?status=approved")
    assert b"ApprovedOne" in r.data and b"PendingOne" not in r.data
    r = client.get("/admin/writeups?status=all")
    assert b"ApprovedOne" in r.data and b"PendingOne" in r.data


def test_queue_requires_admin(app, make_user, make_challenge):
    from tests.helpers import login_as_user
    u = make_user()
    client = login_as_user(app, name=u.name, password="pw")
    r = client.get("/admin/writeups", follow_redirects=False)
    assert r.status_code in (302, 403)  # CTFd admins_only redirects non-admins
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_review.py -v`
Expected: FAIL — queue titles absent from the admin page

- [ ] **Step 3: Implement**

In `ctfd_censored_writeups/views.py`, replace the `admin_page` route:

```python
    @blueprint.route("/admin/writeups", methods=["GET"])
    @admins_only
    def admin_page():
        total = Writeup.query.count()
        quarantined = Writeup.query.filter_by(quarantined=True).count()
        return render_template("admin_writeups.html", total=total, quarantined=quarantined)
```

with:

```python
    @blueprint.route("/admin/writeups", methods=["GET"])
    @admins_only
    def admin_page():
        from .models import WriteupSubmission
        total = Writeup.query.count()
        quarantined = Writeup.query.filter_by(quarantined=True).count()
        status = request.args.get("status", "pending")
        q = WriteupSubmission.query
        if status != "all":
            q = q.filter_by(status=status)
        subs = q.order_by(WriteupSubmission.created_at.asc()).all()
        names = {s.challenge_id: compat.challenge_name(s.challenge_id) for s in subs}
        submitters = {s.user_id: compat.user_name(s.user_id) for s in subs}
        return render_template("admin_writeups.html", total=total, quarantined=quarantined,
                               subs=subs, names=names, submitters=submitters, status=status)
```

In `ctfd_censored_writeups/templates/admin_writeups.html`, before the closing `</div>` insert:

```html
  <h3>Submissions</h3>
  <p>
    Filter:
    {% for st in ["pending", "approved", "rejected", "all"] %}
    <a href="/admin/writeups?status={{ st }}">{{ st }}</a>{% if st == status %} (current){% endif %}{% if not loop.last %} &middot;{% endif %}
    {% endfor %}
  </p>
  {% if not subs %}<p>No {{ status }} submissions.</p>{% endif %}
  {% if subs %}
  <table class="table" border="1">
    <tr><th>Challenge</th><th>Title</th><th>Author</th><th>Submitter</th><th>Submitted</th><th>Status</th><th>Score</th><th></th></tr>
    {% for s in subs %}
    <tr>
      <td>{{ names[s.challenge_id] or ("#" ~ s.challenge_id) }}</td>
      <td>{{ s.title }}</td>
      <td>{{ s.author }}</td>
      <td>{{ submitters[s.user_id] or ("#" ~ s.user_id) }}</td>
      <td>{{ s.created_at }}</td>
      <td>{{ s.status }}</td>
      <td>{{ s.score if s.score is not none else "" }}</td>
      <td><a href="/admin/writeups/submissions/{{ s.id }}">review</a></td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_admin_review.py tests/test_webhook.py -v`
Expected: all PASS (existing admin-page tests still green)

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/views.py ctfd_censored_writeups/templates/admin_writeups.html tests/test_admin_review.py
git commit -m "feat: admin submission queue with status filter"
```

---

### Task 9: Review page (GET) + preview endpoint

**Files:**
- Create: `ctfd_censored_writeups/admin_review.py`
- Create: `ctfd_censored_writeups/templates/admin_submission_review.html`
- Modify: `ctfd_censored_writeups/__init__.py` (wire `admin_review.register`)
- Test: `tests/test_admin_review.py` (append)

**Interfaces:**
- Consumes: `WriteupSubmission` + status constants, `publish.evaluate`, `compat.challenge_name`/`user_name`, `CTFd.utils.markdown`.
- Produces: `admin_review.register(blueprint)` adding `GET /admin/writeups/submissions/<int:sub_id>` and `POST /admin/writeups/submissions/<int:sub_id>/preview` (JSON `{"success": true, "html": str, "warnings": [str]}`; stateless — persists nothing). Internal helper `_render_review(sub, body, status_code=200)` reused by Task 10 for warning re-renders.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_review.py`:

```python
def test_review_page_renders_censored_preview_and_warnings(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, body="pre <!--redact-->FLAG{x}<!--/redact--> post")
    client = _admin_client(app, make_admin)
    r = client.get(f"/admin/writeups/submissions/{sid}")
    assert r.status_code == 200
    assert b"FLAG{x}" in r.data          # raw body shown in the edit textarea
    assert "〔redacted".encode() in r.data  # censored preview rendered
    assert b"Approve" in r.data and b"Reject" in r.data


def test_review_page_shows_malformed_warning(app, make_admin, make_user, make_challenge):
    from ctfd_censored_writeups.publish import WARN_MALFORMED
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, body="broken <!--redact-->no close")
    client = _admin_client(app, make_admin)
    r = client.get(f"/admin/writeups/submissions/{sid}")
    assert WARN_MALFORMED.encode() in r.data


def test_review_page_shows_llm_report_when_present(app, make_admin, make_user, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id)
    with app.app_context():
        s = app.db.session.get(WriteupSubmission, sid)
        s.llm_report = '{"verdict": "looks-good", "summary": "solid writeup"}'
        app.db.session.commit()
    client = _admin_client(app, make_admin)
    r = client.get(f"/admin/writeups/submissions/{sid}")
    assert b"looks-good" in r.data


def test_review_page_404_on_unknown(app, make_admin):
    client = _admin_client(app, make_admin)
    assert client.get("/admin/writeups/submissions/99999").status_code == 404


def test_preview_endpoint_renders_posted_body(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id)
    client = _admin_client(app, make_admin)
    r = client.post(f"/admin/writeups/submissions/{sid}/preview",
                    data={"nonce": _nonce(client),
                          "body": "now with <!--redact-->FLAG{y}<!--/redact--> marker"},
                    )
    assert r.status_code == 200
    j = r.get_json()
    assert j["success"] is True
    assert "FLAG{y}" not in j["html"]
    assert "redacted" in j["html"]
    assert j["warnings"] == []


def test_preview_endpoint_reports_warnings_and_persists_nothing(app, make_admin, make_user, make_challenge):
    from ctfd_censored_writeups.models import WriteupSubmission
    from ctfd_censored_writeups.publish import WARN_MALFORMED
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, body="original body")
    client = _admin_client(app, make_admin)
    r = client.post(f"/admin/writeups/submissions/{sid}/preview",
                    data={"nonce": _nonce(client), "body": "bad <!--redact-->"})
    assert WARN_MALFORMED in r.get_json()["warnings"]
    with app.app_context():
        s = app.db.session.get(WriteupSubmission, sid)
        assert s.body_raw == "original body"
        assert s.body_edited is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_review.py -v`
Expected: new tests FAIL with 404 on the review URLs

- [ ] **Step 3: Implement**

Create `ctfd_censored_writeups/admin_review.py`:

```python
"""
Admin review: side-by-side edit + censored preview, approve/reject with
score and comment, re-open. The preview always runs the REAL pipeline
(publish.evaluate), so what the admin sees is exactly what a non-solver
would be served.
"""
from datetime import datetime, timezone

from flask import abort, current_app, jsonify, redirect, render_template, request, session
from CTFd.models import db
from CTFd.utils import markdown
from CTFd.utils.decorators import admins_only

from .models import (
    WriteupSubmission,
    STATUS_PENDING,
    STATUS_APPROVED,
    STATUS_REJECTED,
)
from . import compat, notify, publish


def _render_review(sub, body, status_code=200):
    ev = publish.evaluate(sub.challenge_id, body)
    return render_template(
        "admin_submission_review.html",
        sub=sub,
        body=body,
        preview_html=markdown(ev.parsed.censored_body),
        warnings=ev.warnings,
        challenge_name=compat.challenge_name(sub.challenge_id) or f"#{sub.challenge_id}",
        submitter_name=compat.user_name(sub.user_id) or f"#{sub.user_id}",
        nonce=session.get("nonce"),
    ), status_code


def register(blueprint):
    @blueprint.route("/admin/writeups/submissions/<int:sub_id>", methods=["GET"])
    @admins_only
    def review_page(sub_id):
        sub = db.session.get(WriteupSubmission, sub_id)
        if sub is None:
            abort(404)
        return _render_review(sub, sub.body_edited or sub.body_raw)

    @blueprint.route("/admin/writeups/submissions/<int:sub_id>/preview", methods=["POST"])
    @admins_only
    def preview(sub_id):
        """Stateless re-render of the censored preview for an edited body."""
        sub = db.session.get(WriteupSubmission, sub_id)
        if sub is None:
            abort(404)
        ev = publish.evaluate(sub.challenge_id, request.form.get("body") or "")
        return jsonify({
            "success": True,
            "html": markdown(ev.parsed.censored_body),
            "warnings": ev.warnings,
        })
```

Create `ctfd_censored_writeups/templates/admin_submission_review.html`:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Review Submission</title>
</head>
<body>
<div class="container">
  <h2>Review submission #{{ sub.id }}</h2>
  <p>
    Challenge: <strong>{{ challenge_name }}</strong> &mdash;
    author: {{ sub.author }} &mdash; submitter: {{ submitter_name }} &mdash;
    status: <strong>{{ sub.status }}</strong>
  </p>
  <p><a href="/admin/writeups">&larr; back to queue</a></p>

  <ul id="wu-warnings" style="color: #b00;">
    {% for w in warnings %}<li>{{ w }}</li>{% endfor %}
  </ul>

  {% if sub.llm_report %}
  <h3>LLM pre-review</h3>
  <pre>{{ sub.llm_report }}</pre>
  {% endif %}

  {% if sub.status == "approved" %}
  <p>This submission is published as writeup #{{ sub.writeup_id }}
     (<a href="/writeups/{{ sub.challenge_id }}/{{ sub.writeup_id }}">view</a>).</p>
  <form method="POST" action="/admin/writeups/submissions/{{ sub.id }}/reopen">
    <input type="hidden" name="nonce" value="{{ nonce }}">
    <button type="submit">Re-open (unpublish)</button>
  </form>
  {% else %}
  <form method="POST" action="/admin/writeups/submissions/{{ sub.id }}/decide">
    <input type="hidden" name="nonce" value="{{ nonce }}">
    <input type="hidden" name="updated_at" value="{{ sub.updated_at.isoformat() }}">
    <div style="display: flex; gap: 1em;">
      <div style="flex: 1;">
        <h3>Body (editable &mdash; wrap missed spoilers in redaction markers)</h3>
        <textarea name="body" id="wu-body" rows="30" style="width: 100%;">{{ body }}</textarea>
      </div>
      <div style="flex: 1;">
        <h3>Censored preview (what a non-solver sees; check images by eye
            &mdash; they cannot be redacted)</h3>
        <div id="wu-preview" style="border: 1px solid #ccc; padding: 0.5em;">{{ preview_html | safe }}</div>
      </div>
    </div>
    <p><button type="button" id="wu-repreview">Re-preview</button></p>
    <p><label>Score (internal): <input type="number" name="score"
        value="{{ sub.score if sub.score is not none else '' }}"></label></p>
    <p><label>Comment (required to reject; shown to the submitter):<br>
        <textarea name="comment" rows="3" cols="70">{{ sub.admin_comment or '' }}</textarea></label></p>
    <button type="submit" name="action" value="approve">Approve &amp; publish</button>
    <button type="submit" name="action" value="reject">Reject</button>
  </form>
  <script>
    document.getElementById("wu-repreview").onclick = async () => {
      const fd = new FormData();
      fd.append("body", document.getElementById("wu-body").value);
      const r = await fetch("/admin/writeups/submissions/{{ sub.id }}/preview", {
        method: "POST",
        headers: {"CSRF-Token": "{{ nonce }}"},
        body: fd
      });
      const j = await r.json();
      document.getElementById("wu-preview").innerHTML = j.html;
      const ul = document.getElementById("wu-warnings");
      ul.textContent = "";
      j.warnings.forEach((w) => {
        const li = document.createElement("li");
        li.textContent = w;
        ul.appendChild(li);
      });
    };
  </script>
  {% endif %}
</div>
</body>
</html>
```

In `ctfd_censored_writeups/__init__.py`, after `submissions.register(blueprint)` add:

```python
    from . import admin_review
    admin_review.register(blueprint)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_admin_review.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/admin_review.py ctfd_censored_writeups/templates/admin_submission_review.html ctfd_censored_writeups/__init__.py tests/test_admin_review.py
git commit -m "feat: admin review page with live censored preview"
```

---

### Task 10: Decision endpoint — approve / reject

**Files:**
- Modify: `ctfd_censored_writeups/admin_review.py` (append route)
- Test: `tests/test_admin_review.py` (append)

**Interfaces:**
- Consumes: `publish.evaluate`/`publish_submission` (Tasks 2–3), `notify.notify_reviewed` (Task 4), `_render_review` (Task 9).
- Produces: `POST /admin/writeups/submissions/<int:sub_id>/decide` with form fields `action` (`approve`|`reject`), `body`, `score`, `comment`, `updated_at` (race token). Redirects to `/admin/writeups` on success; 400 + re-rendered review page (warnings) on blocked approval; 409 on stale `updated_at` or already-approved.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_review.py`:

```python
def _decide(client, app, sid, action, body=None, score="", comment=""):
    from ctfd_censored_writeups.models import WriteupSubmission
    with app.app_context():
        s = app.db.session.get(WriteupSubmission, sid)
        token = s.updated_at.isoformat()
        if body is None:
            body = s.body_edited or s.body_raw
    return client.post(f"/admin/writeups/submissions/{sid}/decide", data={
        "nonce": _nonce(client), "action": action, "body": body,
        "score": score, "comment": comment, "updated_at": token,
    })


def test_approve_publishes_gated_writeup(app, make_admin, make_user, make_challenge, make_solve):
    from tests.helpers import login_as_user
    c = make_challenge()
    solver = make_user(name="solver", email="s@x.io")
    other = make_user(name="other", email="o@x.io")
    make_solve(user_id=solver.id, challenge_id=c.id)
    sid = _seed_submission(app, c.id, solver.id,
                           body="how: <!--redact-->FLAG{deep}<!--/redact--> done")
    client = _admin_client(app, make_admin)
    r = _decide(client, app, sid, "approve", score="7")
    assert r.status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, Writeup
        s = app.db.session.get(WriteupSubmission, sid)
        assert s.status == "approved"
        assert s.score == 7
        assert s.reviewed_at is not None
        w = Writeup.query.filter_by(source_key=f"submission://{sid}").one()
        assert s.writeup_id == w.id
        cid, wid = w.challenge_id, w.id
    solver_client = login_as_user(app, name="solver", password="pw")
    assert b"FLAG{deep}" in solver_client.get(f"/writeups/{cid}/{wid}").data
    other_client = login_as_user(app, name="other", password="pw")
    resp = other_client.get(f"/writeups/{cid}/{wid}")
    assert resp.status_code == 200
    assert b"FLAG{deep}" not in resp.data


def test_approve_blocked_on_malformed_redaction(app, make_admin, make_user, make_challenge):
    from ctfd_censored_writeups.publish import WARN_MALFORMED
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, body="bad <!--redact-->unclosed")
    client = _admin_client(app, make_admin)
    r = _decide(client, app, sid, "approve")
    assert r.status_code == 400
    assert WARN_MALFORMED.encode() in r.data
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, Writeup
        assert app.db.session.get(WriteupSubmission, sid).status == "pending"
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is None


def test_approve_blocked_on_flag_leak(app, make_admin, make_user, make_challenge):
    from tests.helpers import gen_flag
    from ctfd_censored_writeups.publish import WARN_FLAG_LEAK
    c = make_challenge()
    u = make_user()
    with app.app_context():
        gen_flag(app.db, challenge_id=c.id, content="CTF{oops}")
    sid = _seed_submission(app, c.id, u.id, body="flag is CTF{oops} in plain sight")
    client = _admin_client(app, make_admin)
    r = _decide(client, app, sid, "approve")
    assert r.status_code == 400
    assert WARN_FLAG_LEAK.encode() in r.data


def test_admin_edited_body_is_saved_and_published(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, body="original spoiler CTF{fake}")
    client = _admin_client(app, make_admin)
    edited = "original spoiler <!--redact-->CTF{fake}<!--/redact-->"
    r = _decide(client, app, sid, "approve", body=edited)
    assert r.status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, Writeup, WriteupUncensored
        s = app.db.session.get(WriteupSubmission, sid)
        assert s.body_edited == edited
        assert s.body_raw == "original spoiler CTF{fake}"  # original preserved
        w = Writeup.query.filter_by(source_key=f"submission://{sid}").one()
        assert "CTF{fake}" not in w.censored_body
        assert "CTF{fake}" in WriteupUncensored.query.filter_by(writeup_id=w.id).one().uncensored_body


def test_reject_requires_comment_and_publishes_nothing(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id)
    client = _admin_client(app, make_admin)
    assert _decide(client, app, sid, "reject", comment="").status_code == 400
    r = _decide(client, app, sid, "reject", comment="too thin")
    assert r.status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, Writeup
        s = app.db.session.get(WriteupSubmission, sid)
        assert s.status == "rejected"
        assert s.admin_comment == "too thin"
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is None


def test_stale_updated_at_409(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id)
    client = _admin_client(app, make_admin)
    r = client.post(f"/admin/writeups/submissions/{sid}/decide", data={
        "nonce": _nonce(client), "action": "reject", "body": "x",
        "comment": "c", "updated_at": "2000-01-01T00:00:00",
    })
    assert r.status_code == 409


def test_decide_on_approved_submission_409(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, status="approved")
    client = _admin_client(app, make_admin)
    assert _decide(client, app, sid, "reject", comment="c").status_code == 409


def test_decision_fires_reviewed_webhook_without_comment_text(app, make_admin, make_user, make_challenge, monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json)

    from ctfd_censored_writeups import notify
    monkeypatch.setattr(notify.requests, "post", fake_post)
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    c = make_challenge(name="Hooked")
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, title="Hooked Title")
    client = _admin_client(app, make_admin)
    r = _decide(client, app, sid, "reject", comment="SECRETCOMMENT for submitter")
    assert r.status_code == 302
    assert len(calls) == 1
    msg = calls[0]["content"]
    assert "Rejected" in msg and "Hooked Title" in msg and "Hooked" in msg
    assert "SECRETCOMMENT" not in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_review.py -v`
Expected: new tests FAIL with 404 on `/decide`

- [ ] **Step 3: Implement the decide route**

Append inside `register(blueprint)` in `ctfd_censored_writeups/admin_review.py`:

```python
    @blueprint.route("/admin/writeups/submissions/<int:sub_id>/decide", methods=["POST"])
    @admins_only
    def decide(sub_id):
        sub = db.session.get(WriteupSubmission, sub_id)
        if sub is None:
            abort(404)
        if sub.status == STATUS_APPROVED:
            abort(409, description="already approved — re-open first")
        # Race guard: the submitter may have resubmitted while this page was open.
        if request.form.get("updated_at") != sub.updated_at.isoformat():
            abort(409, description="submission changed since the page was loaded — reload")

        action = request.form.get("action")
        body = request.form.get("body") or ""
        comment = (request.form.get("comment") or "").strip()
        score_raw = (request.form.get("score") or "").strip()
        try:
            score = int(score_raw) if score_raw else None
        except ValueError:
            abort(400)

        # Persist admin edits; body_edited stays None while identical to the original.
        sub.body_edited = body if body != sub.body_raw else None

        if action == "approve":
            ev = publish.evaluate(sub.challenge_id, sub.body_edited or sub.body_raw)
            if ev.warnings:
                # Blocked, not quarantined: a human is in the loop to fix it.
                db.session.rollback()
                return _render_review(sub, body, status_code=400)
            w = publish.publish_submission(sub)
            sub.writeup_id = w.id
            sub.status = STATUS_APPROVED
        elif action == "reject":
            if not comment:
                abort(400, description="a comment is required to reject")
            sub.status = STATUS_REJECTED
        else:
            abort(400)

        admin = compat.current_user()
        sub.admin_comment = comment or None
        sub.score = score
        sub.reviewed_by = admin.id
        sub.reviewed_at = datetime.now(timezone.utc)
        db.session.commit()

        notify.notify_reviewed(
            current_app, sub.title,
            compat.challenge_name(sub.challenge_id) or f"#{sub.challenge_id}",
            approved=(sub.status == STATUS_APPROVED), score=sub.score,
        )
        return redirect("/admin/writeups")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_admin_review.py -v`
Expected: all PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest tests/ -x -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add ctfd_censored_writeups/admin_review.py tests/test_admin_review.py
git commit -m "feat: approve/reject decisions with blocked-approval safety"
```

---

### Task 11: Re-open an approved submission

**Files:**
- Modify: `ctfd_censored_writeups/admin_review.py` (append route)
- Test: `tests/test_admin_review.py` (append)

**Interfaces:**
- Consumes: `publish.unpublish_submission` (Task 3).
- Produces: `POST /admin/writeups/submissions/<int:sub_id>/reopen` — approved-only (400 otherwise); unpublishes, clears `writeup_id`/reviewer fields, sets `pending`; redirects back to the review page.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_admin_review.py`:

```python
def test_reopen_unpublishes_and_resets(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id)
    client = _admin_client(app, make_admin)
    assert _decide(client, app, sid, "approve").status_code == 302
    r = client.post(f"/admin/writeups/submissions/{sid}/reopen",
                    data={"nonce": _nonce(client)})
    assert r.status_code == 302
    with app.app_context():
        from ctfd_censored_writeups.models import WriteupSubmission, Writeup, WriteupUncensored
        s = app.db.session.get(WriteupSubmission, sid)
        assert s.status == "pending"
        assert s.writeup_id is None
        assert s.reviewed_by is None and s.reviewed_at is None
        assert Writeup.query.filter_by(source_key=f"submission://{sid}").first() is None
        assert WriteupUncensored.query.count() == 0


def test_reopen_only_valid_for_approved(app, make_admin, make_user, make_challenge):
    c = make_challenge()
    u = make_user()
    sid = _seed_submission(app, c.id, u.id, status="pending")
    client = _admin_client(app, make_admin)
    r = client.post(f"/admin/writeups/submissions/{sid}/reopen",
                    data={"nonce": _nonce(client)})
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_review.py -v`
Expected: new tests FAIL with 404 on `/reopen`

- [ ] **Step 3: Implement the reopen route**

Append inside `register(blueprint)` in `ctfd_censored_writeups/admin_review.py`:

```python
    @blueprint.route("/admin/writeups/submissions/<int:sub_id>/reopen", methods=["POST"])
    @admins_only
    def reopen(sub_id):
        sub = db.session.get(WriteupSubmission, sub_id)
        if sub is None:
            abort(404)
        if sub.status != STATUS_APPROVED:
            abort(400, description="only approved submissions can be re-opened")
        publish.unpublish_submission(sub)
        sub.writeup_id = None
        sub.status = STATUS_PENDING
        sub.reviewed_by = None
        sub.reviewed_at = None
        db.session.commit()
        return redirect(f"/admin/writeups/submissions/{sub.id}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_admin_review.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ctfd_censored_writeups/admin_review.py tests/test_admin_review.py
git commit -m "feat: re-open approved submissions (unpublish)"
```

---

### Task 12: Documentation

**Files:**
- Modify: `ctfd_censored_writeups/docs/writeup-format.md`
- Modify: `README.md`
- Modify: `docs/how-it-works.md`
- Modify: `docs/operator-setup.md`

**Interfaces:**
- Consumes: everything shipped in Tasks 1–11.
- Produces: docs only; no code.

- [ ] **Step 1: Add an Images section to the writeup format doc**

In `ctfd_censored_writeups/docs/writeup-format.md`, insert before the "## Source Key and File Identity" section:

```markdown
## Images

Host images externally (imgur, GitHub, a repo raw URL, …) and reference them
by URL:

```markdown
![exploit output](https://i.imgur.com/example.png)
```

Do **not** embed base64 `data:` URIs — they bloat the database and count
against the submission size cap.

**Images cannot be redacted.** The redaction engine works on text only; a
screenshot that shows the flag leaks it to non-solvers no matter what markers
surround it. Never screenshot the flag or the final solution output.
Reviewers check every image during submission review for exactly this reason.
```

- [ ] **Step 2: Document the submission flow**

In `README.md`, add to the "What It Does" bullet list:

```markdown
- **Player submissions**: solvers can submit writeups from `/writeups/submit` (structured form + markdown body, `.md` upload supported). Admins review at `/admin/writeups`: side-by-side editor with live censored preview, optional internal score, approve/reject with comment. Approved writeups publish instantly under a `submission://<id>` source key that file sync never touches. Optional Discord webhook announces submissions and decisions (`WRITEUPS_DISCORD_WEBHOOK_URL`).
```

In `docs/how-it-works.md`, append a section:

```markdown
## Player Submissions

Submissions live in `plugin_writeup_submissions` **in the uncensored bind** —
an unreviewed body is presumed to contain flags, so it never touches the main
DB. One live submission per (user, challenge); resubmitting a pending or
rejected writeup overwrites it and resets review state.

On approval, the plugin composes a frontmatter document (numeric challenge
ID, title, author + the admin-final body) and runs it through the same
`parse_writeup_file` → redaction → static-flag-scan pipeline as file sync,
then upserts `Writeup`/`WriteupUncensored` with `source_key =
"submission://<id>"`. Approval is **blocked** (not quarantined) while the
body fails to parse or leaks a static flag — there is a human in the loop to
fix it. `sync_from_dir`'s deletion pass skips the `submission://` namespace,
so file sync and submissions coexist.

The admin review page shows the raw body in an editor next to a rendered
censored preview (the real pipeline output). Admin edits are stored in
`body_edited`; the submitter's original stays in `body_raw`. An approved
submission can be re-opened, which unpublishes it and returns it to the
queue. The `llm_report` column is reserved for a future local-LLM pre-review
worker (e.g. `flask writeups llm-review` scanning pending submissions and
writing back `{"verdict", "summary", "suggested_score"}`); nothing writes it
today.
```

In `docs/operator-setup.md`, add to the config key list/table (matching its existing format):

```markdown
| `WRITEUPS_DISCORD_WEBHOOK_URL` | `""` | Discord webhook URL for submission/review announcements. Empty disables. Payloads contain titles, challenge names, author, and score only — never writeup bodies or admin comments. |
```

- [ ] **Step 3: Verify docs render and the suite still passes**

Run: `pytest tests/ -q`
Expected: all pass (docs-only change; run guards against accidental code edits)

- [ ] **Step 4: Commit**

```bash
git add ctfd_censored_writeups/docs/writeup-format.md README.md docs/how-it-works.md docs/operator-setup.md
git commit -m "docs: submission system - images policy, review flow, config"
```
