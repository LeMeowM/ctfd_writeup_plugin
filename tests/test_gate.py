import ctfd_censored_writeups.gate as gate

class FakeUser:
    def __init__(self, admin=False): self.type = "admin" if admin else "user"

def _patch(monkeypatch, *, admin=False, solved=False, ended=False, open_after=False, account=7):
    monkeypatch.setattr(gate.compat, "is_admin", lambda u: admin)
    monkeypatch.setattr(gate.compat, "account_id_for", lambda u: account)
    monkeypatch.setattr(gate.compat, "has_solved", lambda a, c: solved)
    monkeypatch.setattr(gate.compat, "ctf_ended", lambda: ended)
    monkeypatch.setattr(gate, "_open_after_ctf", lambda app: open_after)

def test_unsolved_player_is_censored(monkeypatch):
    _patch(monkeypatch, solved=False)
    assert gate.decide(None, FakeUser(), 1) == gate.CENSORED

def test_solved_player_is_uncensored(monkeypatch):
    _patch(monkeypatch, solved=True)
    assert gate.decide(None, FakeUser(), 1) == gate.UNCENSORED

def test_admin_always_uncensored(monkeypatch):
    _patch(monkeypatch, admin=True, solved=False)
    assert gate.decide(None, FakeUser(admin=True), 1) == gate.UNCENSORED

def test_no_user_is_censored(monkeypatch):
    _patch(monkeypatch, solved=True)
    assert gate.decide(None, None, 1) == gate.CENSORED

def test_no_account_team_mode_is_censored(monkeypatch):
    _patch(monkeypatch, solved=False, account=None)
    assert gate.decide(None, FakeUser(), 1) == gate.CENSORED

def test_post_ctf_open_toggle_uncensors_all(monkeypatch):
    _patch(monkeypatch, solved=False, ended=True, open_after=True)
    assert gate.decide(None, FakeUser(), 1) == gate.UNCENSORED

def test_post_ctf_default_keeps_gate(monkeypatch):
    _patch(monkeypatch, solved=False, ended=True, open_after=False)
    assert gate.decide(None, FakeUser(), 1) == gate.CENSORED


class _FakeApp:
    def __init__(self, val):
        self.config = {"WRITEUPS_OPEN_AFTER_CTF": val}


def test_open_after_ctf_bool_true():
    assert gate._open_after_ctf(_FakeApp(True)) is True


def test_open_after_ctf_bool_false():
    assert gate._open_after_ctf(_FakeApp(False)) is False


def test_open_after_ctf_string_truthy():
    for v in ("true", "True", "1", "yes", "on", "ON"):
        assert gate._open_after_ctf(_FakeApp(v)) is True, v


def test_open_after_ctf_string_garbage_keeps_gate():
    for v in ("garbage", "false", "0", "no", "off"):
        assert gate._open_after_ctf(_FakeApp(v)) is False, v
