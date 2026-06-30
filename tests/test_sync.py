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
