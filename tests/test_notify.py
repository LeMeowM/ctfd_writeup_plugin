import pytest


@pytest.fixture
def capture_posts(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})

    from ctfd_censored_writeups import notify
    monkeypatch.setattr(notify.requests, "post", fake_post)
    return calls


def test_noop_when_unconfigured(app, capture_posts, monkeypatch):
    from ctfd_censored_writeups import notify
    monkeypatch.delenv("WRITEUPS_DISCORD_WEBHOOK_URL", raising=False)
    notify.notify_submitted(app, "T", "chal", "alice")
    assert capture_posts == []


def test_submitted_message(app, capture_posts, monkeypatch):
    from ctfd_censored_writeups import notify
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    notify.notify_submitted(app, "My Writeup", "Web 101", "alice")
    assert len(capture_posts) == 1
    c = capture_posts[0]
    assert c["url"] == "https://discord.test/hook"
    assert c["timeout"] == 5
    msg = c["json"]["content"]
    assert "My Writeup" in msg and "Web 101" in msg and "alice" in msg
    assert "pending review" in msg


def test_reviewed_messages(app, capture_posts, monkeypatch):
    from ctfd_censored_writeups import notify
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    notify.notify_reviewed(app, "T", "Web 101", approved=True, score=8)
    notify.notify_reviewed(app, "T", "Web 101", approved=False)
    approved_msg = capture_posts[0]["json"]["content"]
    rejected_msg = capture_posts[1]["json"]["content"]
    assert "Approved" in approved_msg and "8" in approved_msg
    assert "Rejected" in rejected_msg


def test_failure_is_swallowed(app, monkeypatch):
    from ctfd_censored_writeups import notify

    def boom(url, json=None, timeout=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(notify.requests, "post", boom)
    monkeypatch.setenv("WRITEUPS_DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    notify.notify_submitted(app, "T", "chal", "a")  # must not raise
