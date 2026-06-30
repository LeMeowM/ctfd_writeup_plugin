import hashlib
import hmac

from flask import abort, current_app, jsonify, render_template, request
from CTFd.plugins import bypass_csrf_protection
from CTFd.utils.decorators import admins_only, authed_only
from CTFd.utils import markdown
from .models import Writeup, WriteupUncensored
from . import compat, gate


def _render_body(writeup):
    user = compat.current_user()
    # IDOR discipline: association comes from the stored row, not the URL.
    decision = gate.decide(current_app, user, writeup.challenge_id)
    if decision == gate.UNCENSORED and writeup.challenge_id is not None:
        body = WriteupUncensored.query.filter_by(writeup_id=writeup.id).one().uncensored_body
        unlocked = True
    else:
        body = writeup.censored_body
        unlocked = False
    return markdown(body), unlocked


def register(blueprint):
    @blueprint.route("/writeups/<int:challenge_id>/<int:writeup_id>")
    @authed_only
    def single(challenge_id, writeup_id):
        user = compat.current_user()
        admin = compat.is_admin(user)
        w = Writeup.query.filter_by(id=writeup_id).first()
        if w is None or w.quarantined:
            abort(404)
        if not admin and not w.visible:
            abort(404)
        if not admin and not compat.challenge_is_visible(w.challenge_id):
            abort(404)
        html, unlocked = _render_body(w)
        resp = current_app.make_response(
            render_template("writeup_single.html", writeup=w, body_html=html, unlocked=unlocked)
        )
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    def _visible_for(challenge_id, user=None):
        q = Writeup.query.filter_by(challenge_id=challenge_id, quarantined=False)
        if not compat.is_admin(user):
            q = q.filter_by(visible=True)
        return q.order_by(Writeup.sort_order.asc(), Writeup.id.asc()).all()

    def _entry_meta(w):
        user = compat.current_user()
        unlocked = gate.decide(current_app, user, w.challenge_id) == gate.UNCENSORED
        return {
            "id": w.id, "challenge_id": w.challenge_id, "title": w.title,
            "author": w.author, "tags": w.tags.split(",") if w.tags else [],
            "sort_order": w.sort_order, "unlocked": unlocked,
        }

    @blueprint.route("/writeups/<int:challenge_id>")
    @authed_only
    def listing(challenge_id):
        user = compat.current_user()
        admin = compat.is_admin(user)
        if not admin and not compat.challenge_is_visible(challenge_id):
            items = []
        else:
            items = [_entry_meta(w) for w in _visible_for(challenge_id, user)]
        resp = current_app.make_response(
            render_template("writeups_list.html", challenge_id=challenge_id, items=items)
        )
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @blueprint.route("/writeups")
    @authed_only
    def index():
        """List all challenges that have at least one visible, non-quarantined writeup."""
        from .models import db
        from sqlalchemy import distinct
        user = compat.current_user()
        admin = compat.is_admin(user)
        q = db.session.query(distinct(Writeup.challenge_id)).filter(
            Writeup.quarantined == False  # noqa: E712
        )
        if not admin:
            q = q.filter(Writeup.visible == True)  # noqa: E712
        all_ids = [row[0] for row in q.all()]
        # Exclude writeups whose challenge is not visible (admins bypass this gate).
        if admin:
            challenge_ids = all_ids
        else:
            challenge_ids = [cid for cid in all_ids if compat.challenge_is_visible(cid)]
        resp = current_app.make_response(
            render_template("writeups_index.html", challenge_ids=challenge_ids)
        )
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @blueprint.route("/api/v1/writeups/<int:challenge_id>")
    @authed_only
    def api_list(challenge_id):
        user = compat.current_user()
        admin = compat.is_admin(user)
        if not admin and not compat.challenge_is_visible(challenge_id):
            data = []
        else:
            data = [_entry_meta(w) for w in _visible_for(challenge_id, user)]
        resp = jsonify({"success": True, "data": data})
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @blueprint.route("/api/v1/writeups/<int:challenge_id>/<int:writeup_id>")
    @authed_only
    def api_single(challenge_id, writeup_id):
        user = compat.current_user()
        admin = compat.is_admin(user)
        w = Writeup.query.filter_by(id=writeup_id).first()
        if w is None or w.quarantined:
            abort(404)
        if not admin and not w.visible:
            abort(404)
        if not admin and not compat.challenge_is_visible(w.challenge_id):
            abort(404)
        html, unlocked = _render_body(w)
        resp = jsonify({"success": True, "data": {
            "id": w.id, "title": w.title, "unlocked": unlocked, "body": html,
        }})
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @blueprint.route("/writeups/_webhook", methods=["POST"])
    @bypass_csrf_protection
    def webhook():
        """HMAC-verified webhook: pull + sync on push events from the git host."""
        from .config import get as cfg_get
        from .sync import sync_from_dir
        from .cli import _git_pull_if_present

        secret = cfg_get(current_app, "WRITEUPS_WEBHOOK_SECRET")
        if not secret:
            abort(503)
        sent = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            secret.encode(), request.get_data(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sent, expected):
            abort(401)
        repo_path = cfg_get(current_app, "WRITEUPS_REPO_PATH")
        _git_pull_if_present(repo_path)
        report = sync_from_dir(current_app, repo_path)
        return {
            "success": True,
            "created": report.created,
            "updated": report.updated,
            "deleted": report.deleted,
            "quarantined": report.quarantined,
        }

    @blueprint.route("/admin/writeups", methods=["GET"])
    @admins_only
    def admin_page():
        total = Writeup.query.count()
        quarantined = Writeup.query.filter_by(quarantined=True).count()
        return render_template("admin_writeups.html", total=total, quarantined=quarantined)

    @blueprint.route("/admin/writeups/sync", methods=["POST"])
    @admins_only
    def admin_sync():
        from .config import get as cfg_get
        from .sync import sync_from_dir
        from .cli import _git_pull_if_present

        repo_path = cfg_get(current_app, "WRITEUPS_REPO_PATH")
        _git_pull_if_present(repo_path)
        report = sync_from_dir(current_app, repo_path)
        return {
            "success": True,
            "created": report.created,
            "updated": report.updated,
            "deleted": report.deleted,
            "quarantined": report.quarantined,
        }
