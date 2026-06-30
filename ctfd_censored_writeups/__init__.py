from flask import Blueprint
from .config import get


def load(app):
    # Register the uncensored bind BEFORE models import / create_all.
    # CTFd's TestingConfig leaves SQLALCHEMY_BINDS=None; guard against that.
    binds = app.config.get("SQLALCHEMY_BINDS") or {}
    app.config["SQLALCHEMY_BINDS"] = binds
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
