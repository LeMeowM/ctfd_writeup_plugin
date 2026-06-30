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
