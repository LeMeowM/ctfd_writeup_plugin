# Task 9 Report: Writeup List Route + Gated JSON API

## What was built

Three new routes added to `register(blueprint)` in `ctfd_censored_writeups/views.py`:

- `GET /writeups/<challenge_id>` — HTML list of visible, non-quarantined writeups; metadata only, no bodies. Cache-Control: private, no-store.
- `GET /api/v1/writeups/<challenge_id>` — JSON list, same metadata.
- `GET /api/v1/writeups/<challenge_id>/<writeup_id>` — JSON single; `body` is the censored markdown-rendered HTML unless gate returns UNCENSORED (IDOR discipline: challenge_id taken from the DB row, not the URL). Cache-Control: private, no-store.

`writeups_list.html` created as a self-contained template (no `{% extends "base.html" %}`), consistent with Task 8's `writeup_single.html`.

## Seeding helper decision

Defined a local `_seed` helper in `tests/test_routes_list_api.py` (same logic as in `tests/test_routes_single.py`) rather than importing from the other test file. This avoids any cross-module import fragility (the task brief notes this as a valid option).

## Brief inconsistency fixed

The brief's implementation code wraps the JSON single response as `{"success": True, "data": {..., "body": ...}}`, but the test code does `data = r.get_json(); data["body"]` — accessing `body` directly at the top level. Since the tests are the spec (TDD), I adjusted the implementation to return `body` at the top level (flat object, no `success`/`data` envelope). The `/api/v1/writeups/<challenge_id>` list route keeps the `{"success": True, "data": [...]}` envelope as the tests don't inspect its structure.

## RED/GREEN evidence

RED (before routes implemented):
```
FAILED tests/test_routes_list_api.py::test_list_shows_metadata_not_body
FAILED tests/test_routes_list_api.py::test_api_single_unsolved_is_censored
FAILED tests/test_routes_list_api.py::test_api_single_solved_is_uncensored
3 failed in 2.69s
```

GREEN (after implementation):
```
3 passed in 2.70s
```

Full suite: **45 passed** in 13.31s.

## Files changed

- `ctfd_censored_writeups/views.py` — added `_visible_for`, `_entry_meta`, `listing`, `api_list`, `api_single` inside `register(blueprint)`; added `jsonify` import at top.
- `ctfd_censored_writeups/templates/writeups_list.html` — new self-contained template.
- `tests/test_routes_list_api.py` — new test file with 3 tests.

## Concerns

- The brief's `api_single` JSON envelope `{"success": True, "data": {...}}` was inconsistent with the test's `data["body"]` access. Resolved by flattening the response; Task 10 may need to be aware of this decision if it tests the API shape.
- Only `DeprecationWarning` noise from CTFd 3.7.6's use of `datetime.utcnow()` — no functional issues.

---

## Fix wave 1 — consistent {success,data} JSON envelope (post-review)

### Envelope change (Fix 1)

`api_single` in `ctfd_censored_writeups/views.py` was returning a flat object `{"id","title","unlocked","body"}`. Changed to wrap in the CTFd-standard envelope:

```python
resp = jsonify({"success": True, "data": {
    "id": w.id, "title": w.title, "unlocked": unlocked, "body": html,
}})
```

Gate/IDOR logic, 404 behaviour, and Cache-Control header left untouched.

### Test updates (Fix 1)

Two existing api_single tests updated to read through the envelope:
- `test_api_single_unsolved_is_censored`: `r.get_json()["data"]["body"]`
- `test_api_single_solved_is_uncensored`: `r.get_json()["data"]["body"]`

### New test (Fix 2) — `test_api_list_no_body`

Added to `tests/test_routes_list_api.py`. Logs in an unsolved user, seeds a writeup whose body contains the flag, GETs `/api/v1/writeups/<cid>`, and asserts:
- `response["success"] is True`
- `response["data"]` is a list
- each entry has no `body` key
- raw response bytes do not contain `FLAG{secret}`

### Strengthened assertion (Fix 3)

`test_list_shows_metadata_not_body` changed from `assert b"T" in r.data` (single-byte, proves nothing) to `assert b">T</a>" in r.data` (verifies title is rendered as link text, matching the template's `<a href="...">{{ it.title }}</a>`).

### Result

```
4 passed in 3.41s  (tests/test_routes_list_api.py -v)
46 passed in 14.19s  (full suite)
```

### Final endpoint shapes (for Task 10)

- `GET /api/v1/writeups/<cid>` — `{"success": true, "data": [ {id, challenge_id, title, author, tags, sort_order, unlocked}, ... ]}`
- `GET /api/v1/writeups/<cid>/<wid>` — `{"success": true, "data": {id, title, unlocked, body}}`
