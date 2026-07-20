"""
Player-facing submission routes: the submit form and (Task 7) "my submissions".

Eligibility is enforced server-side on POST regardless of what the dropdown
showed: the challenge must exist, be visible, and be solved by the account.
"""
from flask import abort, current_app, redirect, render_template, request, session
from CTFd.models import db
from CTFd.utils.decorators import authed_only
from sqlalchemy.exc import IntegrityError

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
        sub.account_id = account_id  # refresh in case team membership changed since a prior submit
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
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            abort(409, description="a submission for this challenge already exists")

        notify.notify_submitted(
            current_app, title,
            compat.challenge_name(challenge_id) or f"#{challenge_id}", author,
        )
        return redirect("/writeups/mine")

    @blueprint.route("/writeups/mine")
    @authed_only
    def my_submissions():
        user = compat.current_user()
        subs = (
            WriteupSubmission.query.filter_by(user_id=user.id)
            .order_by(WriteupSubmission.updated_at.desc())
            .all()
        )
        names = compat.challenge_names([s.challenge_id for s in subs])
        return render_template("my_submissions.html", subs=subs, names=names)
