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


def _solve_account_column():
    """The Solves column that holds the account id for the current mode.

    Solves.account_id is a hybrid_property with no SQL expression clause, so it
    cannot be used in a WHERE; we filter on team_id in team mode, user_id
    otherwise. Single source of truth for both has_solved and solved_challenges."""
    return Solves.team_id if is_teams_mode() else Solves.user_id


def has_solved(account_id, challenge_id) -> bool:
    if account_id is None:
        return False
    col = _solve_account_column()
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


def solved_challenges(account_id) -> list[tuple[int, str]]:
    """(id, name) of challenges solved by the account, name-sorted."""
    if account_id is None:
        return []
    col = _solve_account_column()
    rows = (
        db.session.query(Challenges.id, Challenges.name)
        .join(Solves, Solves.challenge_id == Challenges.id)
        .filter(col == account_id)
        .order_by(Challenges.name.asc())
        .all()
    )
    return [(r[0], r[1]) for r in rows]


def challenge_name(challenge_id) -> str | None:
    row = db.session.query(Challenges.name).filter(Challenges.id == challenge_id).first()
    return row[0] if row else None


def challenge_names(challenge_ids) -> dict:
    """Map {id: name} for the given challenge ids in one query (missing ids
    are simply absent). Batched form of challenge_name for list views."""
    ids = {cid for cid in challenge_ids if cid is not None}
    if not ids:
        return {}
    rows = db.session.query(Challenges.id, Challenges.name).filter(Challenges.id.in_(ids)).all()
    return {r[0]: r[1] for r in rows}


def user_name(user_id) -> str | None:
    from CTFd.models import Users
    u = db.session.get(Users, user_id)
    return u.name if u else None


def user_names(user_ids) -> dict:
    """Map {id: name} for the given user ids in one query. Batched user_name."""
    from CTFd.models import Users
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    rows = db.session.query(Users.id, Users.name).filter(Users.id.in_(ids)).all()
    return {r[0]: r[1] for r in rows}
