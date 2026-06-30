# Task 2 Report: Redaction (pure, safety-critical)

## Status: COMPLETE

Commit: `17fb3d3` — feat: fail-closed redaction of inline spans and flag/spoiler fences

## What was built

- `ctfd_censored_writeups/redaction.py` — pure-Python redaction module, implemented
  verbatim from the brief. Strips `<!--redact-->...<!--/redact-->` inline spans and
  ` ```flag `/` ```spoiler ` fenced blocks. Fails closed: unclosed or nested markers
  redact the remainder and set `ok=False`. Exposes `PLACEHOLDER_INLINE`,
  `PLACEHOLDER_BLOCK`, `CensorResult` dataclass, `censor()`, and `verify_no_secret()`.
- `tests/test_redaction.py` — 7 tests from the brief (one test-data line corrected,
  see Concerns).

## RED/GREEN evidence

### RED (module missing) — `.venv/bin/pytest tests/test_redaction.py -v`
```
ImportError while importing test module 'tests/test_redaction.py'.
E   ModuleNotFoundError: No module named 'ctfd_censored_writeups'
!!!! Interrupted: 1 error during collection !!!!
```
(Matches brief Step 2 expectation: "FAIL (module missing)".)

### Intermediate RED — after implementing, 1 test failed on contradictory test data
```
tests/test_redaction.py::test_nested_markers_fail_closed FAILED
AssertionError: assert 'a' not in '〔redacted — solve this challenge to view〕'
6 passed, 1 failed
```
Root cause: the brief's test used single-letter secrets "a"/"b"; the letter "a"
appears inside the user-facing PLACEHOLDER_INLINE string ("redacted", "challenge"),
so the assertion `"a" not in r.censored` can never hold. This is a flaw in the
brief's TEST DATA, not the implementation. Reported to coordinator; coordinator
directed keeping the placeholder verbatim (user-approved string) and fixing only
the test to use distinct tokens SECRETONE/SECRETTWO.

### GREEN — `.venv/bin/pytest tests/test_redaction.py -v`
```
7 passed, 6 warnings in 0.01s
```

### Full suite — `.venv/bin/pytest -v`
```
tests/test_models.py::test_writeup_roundtrip PASSED
tests/test_models.py::test_source_key_unique PASSED
tests/test_redaction.py:: (7 tests) PASSED
tests/test_scaffold.py::test_plugin_loads PASSED
tests/test_scaffold.py::test_factories PASSED
11 passed, 43573 warnings in 1.97s
```
Also verified standalone (`tests/test_redaction.py` alone: 7 passed) and
collection-order independence (`test_redaction test_models`: 9 passed).

## Files changed
- `ctfd_censored_writeups/redaction.py` (new) — implementation, verbatim from brief.
- `tests/test_redaction.py` (new) — 7 tests; `test_nested_markers_fail_closed` uses
  corrected secret tokens.
- `tests/conftest.py` (modified) — added `sys.path.insert(0, str(REPO))` so the
  pure-Python module is importable as `ctfd_censored_writeups.redaction` at
  collection time without the CTFd app/DB fixtures.

## Concerns / deviations from brief

1. **Test-data correction (coordinator-approved).** `test_nested_markers_fail_closed`
   changed from secrets "a"/"b" to "SECRETONE"/"SECRETTWO". The brief's original used
   single letters that collide with letters inside the (user-approved) placeholder
   string, making the assertion impossible. Placeholder left exactly as the brief
   specifies. Implementation unchanged from brief.

2. **conftest.py path addition (beyond the brief's stated file list).** The brief
   claimed the module is "tested standalone with `.venv/bin/pytest tests/test_redaction.py -v`",
   but the repo root was not on sys.path (no setup.py/pyproject; conftest only
   symlinks the package into CTFd's plugins dir and aliases submodules at runtime
   inside the `app` fixture). My test imports `ctfd_censored_writeups.redaction` at
   collection time, so without a path entry both the standalone command AND full-suite
   collection failed with ModuleNotFoundError. Added a single guarded
   `sys.path.insert(0, str(REPO))` to conftest. Verified empirically this does NOT
   cause the double SQLAlchemy table registration the conftest guards against:
   importing the package runs only `flask` + `config` imports (no model registration);
   model tests still resolve `.models` via the app-fixture alias. All 11 tests pass in
   default and reversed order. This is a minimal, justified harness fix; flagging it
   since conftest is shared infra touched by other tasks.

3. No other concerns. Implementation matches the brief's code exactly.

---

## Fix wave 1

### Fix 1 (CRITICAL) — unclosed fenced block now fails closed

`ctfd_censored_writeups/redaction.py`:
- Added module-level `_FENCE_OPEN = re.compile(r"^```(?:flag|spoiler)\s*$", re.MULTILINE)`.
- In `censor()`, after the closed-fence `_FENCE.sub(...)` pass, a `_FENCE_OPEN.search()`
  on the remaining text detects any unclosed opener; if found, text is truncated to
  `PLACEHOLDER_BLOCK`, `spans` incremented, and `ok` set to `False`.
- `verify_no_secret()` extended to also reject bare opener lines via
  `not _FENCE_OPEN.search(censored)`.

`tests/test_redaction.py`:
- Added `test_unclosed_fence_fails_closed`: confirms `"leaked secret" not in r.censored`
  and `r.ok is False` for input `"```flag\nleaked secret to end"`.

Existing closed-fence tests (`test_flag_fence_contents_stripped`,
`test_spoiler_fence_stripped`) unaffected — they use properly closed fences handled
before the new check runs.

### Fix 2 (IMPORTANT) — order-independent sys.modules aliasing in app fixture

`tests/conftest.py`, `app` fixture:
- BEFORE `create_ctfd(...)`: evict any stale `ctfd_censored_writeups*` entries loaded
  at collection time via the repo-root `sys.path` entry (so CTFd loads a clean copy).
- AFTER `create_ctfd(...)`: replaced `setdefault` with direct assignment
  (`sys.modules[_alias] = sys.modules[_full_name]`) so the alias always points to
  the CTFd-loaded module regardless of import order.

Existing teardown that pops `ctfd_censored_writeups*` is unchanged.

### Pytest result

Command: `.venv/bin/pytest -v`

```
12 passed, 43573 warnings in 1.97s
```

All 12 tests pass (redaction: 8 tests, models: 2, scaffold: 2).
`test_unclosed_fence_fails_closed` PASSED.
