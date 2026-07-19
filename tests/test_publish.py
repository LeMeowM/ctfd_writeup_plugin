def test_compose_document_roundtrips_through_parser(app):
    from ctfd_censored_writeups.publish import compose_document
    from ctfd_censored_writeups.parser import parse_writeup_file
    doc = compose_document(42, "My Title", "alice", "hello <!--redact-->FLAG{x}<!--/redact--> world")
    p = parse_writeup_file(doc, "submission://1")
    assert p.ok
    assert p.challenge_ref == "42"          # numeric -> resolved as ID, never ambiguous
    assert p.title == "My Title"
    assert p.author == "alice"
    assert "FLAG{x}" not in p.censored_body
    assert "FLAG{x}" in p.uncensored_body


def test_compose_document_handles_tricky_yaml_title(app):
    from ctfd_censored_writeups.publish import compose_document
    from ctfd_censored_writeups.parser import parse_writeup_file
    doc = compose_document(7, 'Quote " and : colon', None, "body")
    p = parse_writeup_file(doc, "k")
    assert p.ok
    assert p.title == 'Quote " and : colon'
    assert p.author is None


def test_evaluate_clean_body_has_no_warnings(app, make_challenge):
    from ctfd_censored_writeups.publish import evaluate
    c = make_challenge()
    with app.app_context():
        ev = evaluate(c.id, "safe <!--redact-->FLAG{x}<!--/redact--> text")
        assert ev.warnings == []
        assert "FLAG{x}" not in ev.parsed.censored_body


def test_evaluate_flags_malformed_redaction(app, make_challenge):
    from ctfd_censored_writeups.publish import evaluate, WARN_MALFORMED
    c = make_challenge()
    with app.app_context():
        ev = evaluate(c.id, "oops <!--redact-->never closed")
        assert WARN_MALFORMED in ev.warnings


def test_evaluate_flags_static_flag_leak(app, make_challenge):
    from tests.helpers import gen_flag
    from ctfd_censored_writeups.publish import evaluate, WARN_FLAG_LEAK
    c = make_challenge()
    with app.app_context():
        gen_flag(app.db, challenge_id=c.id, content="CTF{leaky}")
        ev = evaluate(c.id, "the flag is CTF{leaky}, whoops")
        assert WARN_FLAG_LEAK in ev.warnings


def test_source_key_namespace(app):
    from ctfd_censored_writeups.publish import source_key_for, SUBMISSION_PREFIX
    assert source_key_for(9) == "submission://9"
    assert source_key_for(9).startswith(SUBMISSION_PREFIX)
