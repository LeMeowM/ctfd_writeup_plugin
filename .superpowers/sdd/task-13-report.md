# Task 13 Report: Documentation Deliverable

## Files Created

- `ctfd_censored_writeups/docs/writeup-format.md` — frontmatter schema, challenge resolution rules, redaction markers (inline + fenced), fail-closed behavior (quoting exact PLACEHOLDER_INLINE value from code), source_key identity, complete example file.
- `docs/how-it-works.md` — solve gate (user/team/admin/post-CTF), two-bind storage model and defense-in-depth rationale, sync flow and algorithm, quarantine triggers, API shapes (list + single JSON), IDOR discipline, known limitations section.
- `docs/operator-setup.md` — install steps, dev/test setup (CTFd not on PyPI, .ctfd-src clone), all four config keys with defaults and rationale, webhook wiring, initial seed command.
- `README.md` — one-screen overview with invariant, feature summary, links to all three docs and design spec.
- `ctfd_censored_writeups/templates/admin_writeups.html` — added "Setup & format docs" link before the Sync button.

## Code-vs-Expectation Discrepancies Found

None substantive. One note each:

1. `compat.py` documents its own divergence from the brief: `ctf_ended` is `CTFd.utils.dates.ctf_ended`, not `is_ctf_finished`; `has_solved` uses `Solves.user_id`/`Solves.team_id`, not `Solves.account_id`. These are already noted in the compat module's docstring; documented as-built.
2. The `/writeups` index shows "Challenge #N" (no name join) — confirmed by `writeups_index.html` template; documented as a known limitation in how-it-works.md.
3. Flag scan only covers static flags — confirmed in sync.py comment and verified; documented as a known limitation.

## Suite Result

58 passed, 0 failed in 25.98s (DeprecationWarnings from CTFd internals only, no plugin warnings).

## Concerns

None. All docs reflect the actual code.

## Report Path

`/home/hugo/Documents/polygl0ts/CTFd_writeup_plugin/.superpowers/sdd/task-13-report.md`

## Fix Wave 1 — Docs Accuracy Corrections

Commit: `78da44b` — docs: fix title optionality, placeholder-block rendering, and broken links

### Fixes Applied

1. **Fix 1 (IMPORTANT)** — `title` field optionality (`ctfd_censored_writeups/docs/writeup-format.md`)
   - Changed Default from `(required)` to `""` and Notes to "Optional; stored as empty string if omitted"
   - Code behavior verified: `parser.py:60` uses `str(data.get("title", "")).strip()`

2. **Fix 2 (IMPORTANT)** — PLACEHOLDER_BLOCK rendering (`ctfd_censored_writeups/docs/writeup-format.md`)
   - Changed display from single backticks to triple-backtick fenced code block using 4-backtick outer fence
   - Code verified: `redaction.py:5` defines PLACEHOLDER_BLOCK as `"```\n〔redacted — solve this challenge to view〕\n```"`

3. **Fix 3 (IMPORTANT)** — Admin page docs link (`ctfd_censored_writeups/templates/admin_writeups.html`)
   - Corrected GitHub link path from `ctfd_censored_writeups/docs/operator-setup.md` to `docs/operator-setup.md`
   - Verified actual location: `docs/operator-setup.md` exists at repo root

4. **Fix 4 (MINOR)** — Complete example outer fence (`ctfd_censored_writeups/docs/writeup-format.md`)
   - Changed outer fence from 3 backticks to 4 backticks to prevent premature fence closure from internal ```flag block

5. **Fix 5 (MINOR)** — WRITEUPS_OPEN_AFTER_CTF truthy values (`docs/operator-setup.md`)
   - Added `"true"` to documented truthy-values list: now `True` (or `"1"`, `"true"`, `"yes"`, `"on"`)
   - Code verified: `gate.py:10` checks `("1", "true", "yes", "on")`

### Test Result

58 passed in 25.95s (no new failures; admin-template edit confirmed non-breaking)

### File Locations Confirmed

- `ctfd_censored_writeups/docs/writeup-format.md` — exists and fixed
- `docs/operator-setup.md` — exists and fixed
- `docs/how-it-works.md` — exists (no changes needed)
- `docs/superpowers/specs/2026-06-30-ctfd-censored-writeups-design.md` — exists (no changes needed)
- `README.md` links — all four doc links verified to resolve to real existing files
- Admin template link to operator-setup.md — corrected to point to real location

---

## Final-review fix wave

All six items completed. Final suite: **81 passed, 0 failed**.

### Item 1 — Enforce challenge visibility on all routes, with admin bypass
Commit: `0b50129 feat: enforce challenge visibility on writeup routes (admins bypass)`

Added `compat.challenge_is_visible(challenge_id)` (queries `Challenges.state == "visible"`). Updated all five routes in `views.py`: single and api_single abort(404) for non-admins when the challenge is hidden; listing, api_list, and index exclude hidden-challenge writeups for non-admins. Admins bypass both gates. Updated `make_challenge` fixture to accept `state` kwarg; fixed `make_admin` fixture name collision (default name changed from "admin" to "testadmin" to avoid conflict with the admin created by `create_ctfd`). New tests: `tests/test_challenge_visibility.py` — 10 tests covering all five routes for user and admin.

### Item 2 — Admin preview of unpublished (visible=False) writeups
Commit: `81f901a feat: admin preview of unpublished writeups`

The `_visible_for` helper and single/api_single gate introduced in Item 1 already include the admin bypass for `visible=False`; only tests were needed. New tests: `tests/test_admin_preview_unpublished.py` — 10 tests covering all five routes (single, api_single, listing, api_list, index) for both user (hidden) and admin (visible) scenarios.

### Item 3 — Fence info-string must not fail open
Commit: `0348755 fix: redaction fence fails closed on extended info strings`

Changed `_FENCE` and `_FENCE_OPEN` regexes in `redaction.py` from `^```(?:flag|spoiler)\s*$` (exact match) to `^```(?:flag|spoiler)(?:\s.*)?$` (first-token match). This causes `` ```flag bash `` and `` ```spoiler python3 `` to be treated as redaction fences instead of passing through uncensored. Two new tests added to `tests/test_redaction.py`; all 8 existing tests remain green.

### Item 4 — Single after_request for Cache-Control (covers 404s, removes duplication)
Commit: `59acbef refactor: set Cache-Control via blueprint after_request (covers 404s)`

Added `@blueprint.after_request` handler `_set_cache_control` in `views.py` that sets `Cache-Control: private, no-store` on every writeups-blueprint response including `abort(404)` responses. Removed all six redundant per-route `resp.headers["Cache-Control"] = ...` assignments (routes now return plain `render_template`/`jsonify`). New assertion in `test_routes_single.py`: a request for a nonexistent writeup ID returns 404 AND carries the header.

### Item 5 — Remove committed dev secret
Commit: `dcf9f46 chore: untrack local CTFd dev secret key`

Ran `git rm --cached .ctfd_secret_key` to stop tracking the file and added `.ctfd_secret_key` to `.gitignore`. Working-copy file preserved for local CTFd dev use.

### Item 6 — IDOR test status assert
No separate commit; `assert r.status_code == 200` was added to `test_idor_uses_row_challenge_not_url` as part of the Item 4 commit (`59acbef`). The assert appears at line 41 of `tests/test_routes_single.py`, immediately before the flag-absence check, so the test cannot pass by accidentally receiving a 404.
