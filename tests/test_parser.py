from ctfd_censored_writeups.parser import parse_writeup_file

DOC = """---
challenge: 42
title: Unintended RSA
author: alice
sort_order: 10
tags: [crypto, rsa]
visible: true
---
body before <!--redact-->secret<!--/redact--> after
"""

def test_parses_frontmatter_and_censors_body():
    p = parse_writeup_file(DOC, "crypto/rsa.md")
    assert p.source_key == "crypto/rsa.md"
    assert p.challenge_ref == "42"
    assert p.title == "Unintended RSA"
    assert p.author == "alice"
    assert p.sort_order == 10
    assert p.tags == ["crypto", "rsa"]
    assert p.visible is True
    assert "secret" in p.uncensored_body
    assert "secret" not in p.censored_body
    assert p.ok

def test_string_challenge_ref_preserved():
    doc = "---\nchallenge: My Challenge Name\ntitle: t\n---\nbody"
    p = parse_writeup_file(doc, "x.md")
    assert p.challenge_ref == "My Challenge Name"

def test_missing_frontmatter_is_not_ok():
    p = parse_writeup_file("just a body, no frontmatter", "x.md")
    assert p.ok is False
    assert p.challenge_ref == ""

def test_defaults_applied():
    p = parse_writeup_file("---\nchallenge: 1\ntitle: t\n---\nb", "x.md")
    assert p.sort_order == 0
    assert p.visible is True
    assert p.tags == []
