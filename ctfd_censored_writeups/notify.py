"""
Best-effort Discord webhook announcements. Payloads never contain writeup
bodies or admin comments (the channel may be semi-public; bodies may contain
flags) — titles, challenge names, author, and score only. A dead webhook must
never break a submission or a review: failures are logged and swallowed.
"""
import requests

from .config import get

TIMEOUT_SECONDS = 5


def _post(app, content: str):
    url = get(app, "WRITEUPS_DISCORD_WEBHOOK_URL")
    if not url:
        return
    try:
        requests.post(url, json={"content": content}, timeout=TIMEOUT_SECONDS)
    except Exception:
        app.logger.warning("writeups: discord webhook delivery failed", exc_info=True)


def notify_submitted(app, title, challenge_name, author):
    _post(app, f"\U0001F4DD New writeup pending review: *{title}* for *{challenge_name}* by {author}")


def notify_reviewed(app, title, challenge_name, approved: bool, score=None):
    if approved:
        msg = f"✅ Approved: *{title}* for *{challenge_name}*"
        if score is not None:
            msg += f" — score: {score}"
    else:
        msg = f"❌ Rejected: *{title}* for *{challenge_name}*"
    _post(app, msg)
