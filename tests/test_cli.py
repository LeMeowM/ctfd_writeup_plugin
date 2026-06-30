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
