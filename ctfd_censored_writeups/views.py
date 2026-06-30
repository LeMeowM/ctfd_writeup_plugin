from flask import render_template, abort
from CTFd.utils.decorators import authed_only
from CTFd.utils import markdown
from .models import Writeup, WriteupUncensored
from . import compat, gate
from flask import current_app


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
        w = Writeup.query.filter_by(id=writeup_id).first()
        if w is None or w.quarantined or not w.visible:
            abort(404)
        html, unlocked = _render_body(w)
        resp = current_app.make_response(
            render_template("writeup_single.html", writeup=w, body_html=html, unlocked=unlocked)
        )
        resp.headers["Cache-Control"] = "private, no-store"
        return resp
