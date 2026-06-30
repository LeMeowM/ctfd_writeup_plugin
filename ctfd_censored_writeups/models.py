from datetime import datetime, timezone
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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class WriteupUncensored(db.Model):
    __bind_key__ = "uncensored"
    __tablename__ = "plugin_writeups_uncensored"

    writeup_id = db.Column(db.Integer, primary_key=True)  # no cross-bind FK by design
    uncensored_body = db.Column(db.Text, nullable=False, default="")
