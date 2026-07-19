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
