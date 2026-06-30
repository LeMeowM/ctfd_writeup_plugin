import pathlib
from tests.helpers import gen_flag


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
    from ctfd_censored_writeups.sync import sync_from_dir
    from ctfd_censored_writeups.models import Writeup, WriteupUncensored

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
    from ctfd_censored_writeups.sync import sync_from_dir
    from ctfd_censored_writeups.models import Writeup

    chal = make_challenge()
    repo = tmp_path / "repo"
    _write(repo, "a.md", DOC.format(chal=chal.id))
    with app.app_context():
        sync_from_dir(app, str(repo))
        report2 = sync_from_dir(app, str(repo))
        assert report2.created == 0 and report2.updated == 0
        assert Writeup.query.count() == 1


def test_sync_deletes_removed_files(app, make_challenge, tmp_path):
    from ctfd_censored_writeups.sync import sync_from_dir
    from ctfd_censored_writeups.models import Writeup, WriteupUncensored

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
    from ctfd_censored_writeups.sync import sync_from_dir
    from ctfd_censored_writeups.models import Writeup

    repo = tmp_path / "repo"
    _write(repo, "a.md", DOC.format(chal="DoesNotExist"))
    with app.app_context():
        report = sync_from_dir(app, str(repo))
        assert report.quarantined == 1
        w = Writeup.query.filter_by(source_key="a.md").one()
        assert w.quarantined is True
        assert w.challenge_id is None


def test_flag_in_censored_is_quarantined(app, make_challenge, tmp_path):
    """A writeup whose censored body contains a static flag is stored quarantined.

    NOTE: dynamic/regex flags are not detected by this scan; only static flags
    whose content string appears verbatim in the censored body are caught.
    """
    from ctfd_censored_writeups.sync import sync_from_dir
    from ctfd_censored_writeups.models import Writeup

    chal = make_challenge(name="flagtest")
    with app.app_context():
        gen_flag(app.db, challenge_id=chal.id, content="flag{secret_x}", type="static")

    repo = tmp_path / "repo"
    # The flag appears in the non-redacted part of the body (author mistake).
    doc = "---\nchallenge: {}\ntitle: T\n---\nbody flag{{secret_x}} end\n".format(chal.id)
    _write(repo, "flagleak.md", doc)

    with app.app_context():
        report = sync_from_dir(app, str(repo))
        assert report.quarantined == 1
        w = Writeup.query.filter_by(source_key="flagleak.md").one()
        assert w.quarantined is True
        # Error is recorded but must NOT echo the flag value (leak-safe).
        assert len(report.errors) >= 1
        assert all("flag{secret_x}" not in e for e in report.errors)


def test_midfile_exception_rolls_back_and_continues(app, make_challenge, tmp_path, monkeypatch):
    """A post-flush exception on the first file rolls back its partial Writeup row
    and does not prevent the second file from syncing successfully.

    We trigger the failure by monkeypatching WriteupUncensored.__init__ to raise
    on its FIRST construction only. This fires AFTER db.session.flush() has already
    assigned w.id and written the Writeup row inside the savepoint — exactly the
    cross-bind inconsistency window (flushed Writeup, no matching WriteupUncensored)
    that the per-file savepoint is designed to prevent.

    Without sp.rollback() in the except block the orphaned Writeup persists and
    Writeup.query.count() == 2; with it, the savepoint rollback undoes the flush
    and the count stays at 1.
    """
    import ctfd_censored_writeups.models as models_mod
    from ctfd_censored_writeups.models import Writeup, WriteupUncensored

    a = make_challenge(name="A")
    b = make_challenge(name="B")

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.md").write_text(f"---\nchallenge: {a.id}\ntitle: A\n---\nbody")
    (repo / "b.md").write_text(f"---\nchallenge: {b.id}\ntitle: B\n---\nbody")

    real_init = models_mod.WriteupUncensored.__init__
    state = {"n": 0}

    def boom_init(self, *args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom after flush")  # fails the first file post-flush
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(models_mod.WriteupUncensored, "__init__", boom_init)

    from ctfd_censored_writeups.sync import sync_from_dir
    with app.app_context():
        report = sync_from_dir(app, str(repo))
        # exactly one file failed post-flush; its partial Writeup must be rolled back
        assert Writeup.query.count() == 1
        assert WriteupUncensored.query.count() == 1
        # no orphan: the surviving Writeup has a matching uncensored row
        surviving = Writeup.query.one()
        assert WriteupUncensored.query.filter_by(writeup_id=surviving.id).first() is not None
        assert report.created == 1
        assert len(report.errors) == 1


def test_malformed_file_does_not_crash_sync(app, make_challenge, tmp_path):
    """A directory with one malformed file and one good file syncs the good file
    and records an error for the bad one without aborting the whole run.

    The malformed file has sort_order: not_a_number which causes a ValueError
    in parse_writeup_file (int() cast on a non-numeric string fails).
    """
    from ctfd_censored_writeups.sync import sync_from_dir
    from ctfd_censored_writeups.models import Writeup

    chal = make_challenge()
    repo = tmp_path / "repo"
    _write(repo, "good.md", DOC.format(chal=chal.id))
    _write(
        repo,
        "bad.md",
        "---\nchallenge: {}\ntitle: T\nsort_order: not_a_number\n---\nbody\n".format(chal.id),
    )
    with app.app_context():
        report = sync_from_dir(app, str(repo))
        assert report.created == 1
        assert len(report.errors) >= 1
        assert Writeup.query.count() == 1
        assert Writeup.query.filter_by(source_key="good.md").count() == 1
