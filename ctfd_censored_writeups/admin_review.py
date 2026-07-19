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
