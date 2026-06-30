from . import compat
from .config import get

CENSORED = "censored"
UNCENSORED = "uncensored"


def _open_after_ctf(app) -> bool:
    val = get(app, "WRITEUPS_OPEN_AFTER_CTF")
    return str(val).lower() in ("1", "true", "yes", "on") if not isinstance(val, bool) else val


def decide(app, user, challenge_id: int) -> str:
    if user is None:
        return CENSORED
    if compat.is_admin(user):
        return UNCENSORED
    if compat.ctf_ended() and _open_after_ctf(app):
        return UNCENSORED
    account_id = compat.account_id_for(user)
    if account_id is None:
        return CENSORED
    return UNCENSORED if compat.has_solved(account_id, challenge_id) else CENSORED
