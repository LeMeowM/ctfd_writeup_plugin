from ctfd_censored_writeups.redaction import censor, verify_no_secret, PLACEHOLDER_INLINE

def test_inline_span_removed():
    r = censor("intended path was <!--redact-->the LSB oracle<!--/redact--> here")
    assert "LSB oracle" not in r.censored
    assert PLACEHOLDER_INLINE in r.censored
    assert r.redacted_spans == 1
    assert r.ok

def test_flag_fence_contents_stripped():
    src = "before\n```flag\npython solve.py\nFLAG{x}\n```\nafter"
    r = censor(src)
    assert "FLAG{x}" not in r.censored
    assert "solve.py" not in r.censored
    assert "before" in r.censored and "after" in r.censored

def test_spoiler_fence_stripped():
    r = censor("```spoiler\nsecret approach\n```")
    assert "secret approach" not in r.censored

def test_unclosed_inline_fails_closed():
    # No closing marker: everything from the open marker on is treated as redacted.
    r = censor("safe text <!--redact-->leaking secret to end")
    assert "leaking secret" not in r.censored
    assert r.ok is False  # signals the author to fix the source

def test_nested_markers_fail_closed():
    r = censor("<!--redact-->SECRETONE<!--redact-->SECRETTWO<!--/redact-->c<!--/redact-->")
    assert "SECRETONE" not in r.censored and "SECRETTWO" not in r.censored
    assert r.ok is False

def test_verify_detects_remnant():
    assert verify_no_secret("clean text") is True
    assert verify_no_secret("oops <!--redact--> leftover") is False

def test_no_markers_is_identity():
    src = "# Title\n\nplain body\n"
    r = censor(src)
    assert r.censored == src
    assert r.redacted_spans == 0 and r.ok

def test_unclosed_fence_fails_closed():
    r = censor("```flag\nleaked secret to end")
    assert "leaked secret" not in r.censored
    assert r.ok is False
