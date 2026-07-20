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
    body_edited = db.Column(db.Text, nullable=True)   # admin-edited; published body is published_body (edit if not None, else raw)
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

    @property
    def is_pending(self) -> bool:
        return self.status == STATUS_PENDING

    @property
    def is_approved(self) -> bool:
        return self.status == STATUS_APPROVED

    @property
    def is_rejected(self) -> bool:
        return self.status == STATUS_REJECTED

    @property
    def published_body(self) -> str:
        """Body to publish/preview: the admin edit if one was made, otherwise
        the submitter's original. An edit to an empty string is a real edit
        (distinct from 'not edited' = None) and is respected — falling back to
        body_raw there would silently republish content the admin removed."""
        return self.body_edited if self.body_edited is not None else self.body_raw
