"""
CTFd 3.7.6 compatibility shim.

This is the ONLY module allowed to touch CTFd version-specific internals.

Name adjustments vs. the task brief (confirmed against .ctfd-src/CTFd):
- ctf_ended: brief assumed ctfd_config.is_ctf_finished, which does NOT exist
  in 3.7.6. The correct helper is CTFd.utils.dates.ctf_ended (line 51 of
  .ctfd-src/CTFd/utils/dates/__init__.py).
- has_solved: brief filtered on Solves.account_id, but Submissions.account_id
  is a hybrid_property with NO .expression clause (.ctfd-src/CTFd/models/__init__.py
  lines 849-857) — it cannot be used in SQL WHERE. We check Solves.user_id in
  user mode and Solves.team_id in team mode instead.
"""
from CTFd.models import db, Solves, Challenges
from CTFd.utils.user import get_current_user
from CTFd.utils.config import is_teams_mode
from CTFd.utils.dates import ctf_ended as _ctfd_ctf_ended


def current_user():
    return get_current_user()


def is_admin(user) -> bool:
    return bool(user) and getattr(user, "type", None) == "admin"


def account_id_for(user):
    if user is None:
        return None
    if is_teams_mode():
        team_id = getattr(user, "team_id", None)
        return team_id  # None when the user has no team -> caller treats as unsolved
    return user.account_id


def has_solved(account_id, challenge_id) -> bool:
    if account_id is None:
        return False
    # Solves.account_id has no SQL expression clause, so filter on the actual
    # column that holds the account id for the current mode.
    if is_teams_mode():
        col = Solves.team_id
    else:
        col = Solves.user_id
    return (
        db.session.query(Solves.id)
        .filter(col == account_id, Solves.challenge_id == challenge_id)
        .first()
        is not None
    )


def ctf_ended() -> bool:
    # CTFd 3.7.6 exposes this as CTFd.utils.dates.ctf_ended, not
    # CTFd.utils.config.is_ctf_finished (which doesn't exist in 3.7.6).
    return bool(_ctfd_ctf_ended())


def challenge_exists(challenge_id) -> bool:
    return db.session.get(Challenges, challenge_id) is not None


def resolve_challenge_id(challenge_ref: str):
    ref = (challenge_ref or "").strip()
    if not ref:
        return None
    if ref.isdigit():
        cid = int(ref)
        return cid if challenge_exists(cid) else None
    rows = db.session.query(Challenges.id).filter(Challenges.name == ref).all()
    if len(rows) == 1:
        return rows[0][0]
    return None  # zero or ambiguous matches


def challenge_is_visible(challenge_id) -> bool:
    """Return True iff the challenge exists AND its state is 'visible'.

    Confirmed against .ctfd-src/CTFd/models/__init__.py line 122:
    Challenges.state is a String(80) column with default "visible";
    "hidden" is the other canonical value in 3.7.6.
    """
    row = (
        db.session.query(Challenges.state)
        .filter(Challenges.id == challenge_id)
        .first()
    )
    return row is not None and row[0] == "visible"


def static_flag_values(challenge_id) -> list:
    """Return the static flag strings for a challenge (empty list if none/unknown).

    Confirmed against .ctfd-src/CTFd/models/__init__.py lines 330-346:
    Flags has challenge_id (Integer FK), type (String(80)), content (Text) —
    all names match the brief verbatim.
    """
    from CTFd.models import Flags
    rows = Flags.query.filter_by(challenge_id=challenge_id, type="static").all()
    return [f.content for f in rows if getattr(f, "content", None)]
