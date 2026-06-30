# Task 6 Report: Sync Engine

## What Was Built

### (A) Core sync engine — `ctfd_censored_writeups/sync.py`
- `@dataclass SyncReport(created, updated, deleted, quarantined, errors)`.
- `sync_from_dir(app, repo_path)`: walks `*.md` files under `repo_path` via `os.walk`, upserts `Writeup` (main DB) + `WriteupUncensored` (uncensored bind) keyed by `source_key` (repo-relative path).
- **Step 4 refinement applied**: dirty-flag (`changed`) computed before mutating the row; `updated` only increments when content actually differs, so a second identical run reports `created=0, updated=0`.
- Deletion pass: rows whose `source_key` is not in the seen-set are deleted from both binds.

### (B) Flag-scan addendum — `ctfd_censored_writeups/compat.py` + `sync.py`
- Added `static_flag_values(challenge_id) -> list` to `compat.py` (lazy-imported `CTFd.models.Flags`).
- **CTFd 3.7.6 name verification**: `Flags` model at `.ctfd-src/CTFd/models/__init__.py` lines 330–346 has `challenge_id` (Integer FK), `type` (String(80)), `content` (Text) — all names match the brief verbatim. No adjustments needed.
- In `sync.py`, after resolving `challenge_id`, `compat.static_flag_values(challenge_id)` is called; if any value is a substring of `parsed.censored_body`, the writeup is quarantined and an error appended.
- **Limitation comment**: dynamic/regex flags are not scanned; only static flag `content` strings that appear verbatim are caught.

### (C) Per-file crash safety — `sync.py`
- The entire per-file processing body (read → parse → resolve → flag-scan → upsert) is wrapped in `try/except Exception as e`, appending `f"{source_key}: {e}"` to `report.errors` on failure.
- `seen.add(source_key)` remains outside the try so a malformed file's existing DB row is not accidentally deleted.
- `ValueError` from `int("not_a_number")` in `parse_writeup_file` is the tested trigger.

## Tests (`tests/test_sync.py`) — 6 tests total

| Test | What it checks |
|---|---|
| `test_sync_creates_rows_and_splits_binds` | created=1, SECRET not in censored_body, SECRET in uncensored_body |
| `test_sync_is_idempotent` | second run: created=0, updated=0, row count=1 |
| `test_sync_deletes_removed_files` | deleted=1, both Writeup and WriteupUncensored gone |
| `test_unresolved_challenge_is_quarantined` | quarantined=1, w.quarantined=True, w.challenge_id=None |
| `test_flag_in_censored_is_quarantined` (B) | gen_flag used; writeup with flag in censored body is quarantined |
| `test_malformed_file_does_not_crash_sync` (C) | bad sort_order raises ValueError; good file syncs, errors reported, count=1 |

All imports are lazy (inside test functions) to avoid double SQLAlchemy table registration — consistent with existing test patterns.

## RED/GREEN Evidence
- RED: `ModuleNotFoundError: No module named 'ctfd_censored_writeups.sync'` (6 collection errors).
- GREEN: `6 passed` for `tests/test_sync.py`, then `37 passed` for the full suite.

## Files Changed
- Created: `ctfd_censored_writeups/sync.py`
- Modified: `ctfd_censored_writeups/compat.py` (added `static_flag_values`)
- Created: `tests/test_sync.py`

## Fix Wave 1 (2026-06-30)

### Fix 1 (IMPORTANT) — per-file savepoint isolation

`sync_from_dir` now calls `db.session.begin_nested()` before each file's upsert block and commits the savepoint on success or rolls it back on exception. `seen.add(source_key)` remains outside the savepoint so a crashing file's existing DB row is not accidentally deleted by the deletion pass. This closes the cross-bind inconsistency window where a `Writeup` row could be flushed (getting a PK) but its `WriteupUncensored` never written.

### Fix 2 (MINOR) — None-safe flag scan guard

The flag scan condition was strengthened from `if challenge_id is not None` to `if challenge_id is not None and parsed.ok and parsed.censored_body`, preventing a `TypeError` when `censored_body` is `None` after a failed parse.

### Fix 3 (MINOR) — leak-safe flag error message

The error appended on flag detection no longer embeds the flag string. Old: `f"{source_key}: censored body contains static flag '{flag_val}'"`. New: `f"{source_key}: censored body contains the challenge's static flag (redacted)"`. The existing test `test_flag_in_censored_is_quarantined` was extended to assert `"flag{secret_x}" not in e` for all errors.

### New test — `test_midfile_exception_rolls_back_and_continues`

Added to `tests/test_sync.py`. Creates two challenges (chala, chalb) with two valid writeup files. Monkeypatches `sync_mod.compat.static_flag_values` to raise `RuntimeError` only for chala's `challenge_id` — the exception fires after `db.session.flush()` assigns `w.id` but before `WriteupUncensored` is added, exercising the exact cross-bind inconsistency window. Asserts: (a) `sync_from_dir` does not raise, (b) `Writeup` for `a.md` is absent (rolled back) with no orphan `WriteupUncensored`, (c) `b.md` synced fine (`report.created == 1`, `WriteupUncensored` present).

### Commands and results

```
.venv/bin/pytest tests/test_sync.py -v   → 7 passed
.venv/bin/pytest -q                       → 38 passed
```

Commit: `5e1e660 fix: per-file savepoint isolation + leak-safe flag-scan guards`

### Files changed

- Modified: `ctfd_censored_writeups/sync.py`
- Modified: `tests/test_sync.py` (new test + updated flag-leak assertion)

## Fix Wave 2 (2026-06-30)

### Injection point changed — `WriteupUncensored.__init__` (post-flush)

The previous `test_midfile_exception_rolls_back_and_continues` injected its failure at `compat.static_flag_values`, which runs PRE-mutation (before `db.session.flush()`). Because no DB write had occurred yet, the savepoint had no partial work to roll back and the test passed trivially — it would have passed even without the savepoint.

The new version monkeypatches `models_mod.WriteupUncensored.__init__` to raise `RuntimeError("boom after flush")` on its first construction only, then delegates to the real `__init__` for subsequent calls. This fires at `sync.py` line 88 (`u = WriteupUncensored(writeup_id=w.id)`) — AFTER `db.session.flush()` at line 84 has assigned `w.id` and written the Writeup row inside the savepoint. This is the exact post-flush, pre-WriteupUncensored window that creates a cross-bind orphan if the savepoint rollback is absent.

### Evidence

**With savepoint (`sp.rollback()` present — normal production code):**
```
.venv/bin/pytest tests/test_sync.py -v   → 7 passed
.venv/bin/pytest -q                       → 38 passed
```

**Without savepoint (`sp.rollback()` commented out — temporary ablation):**
```
.venv/bin/pytest tests/test_sync.py::test_midfile_exception_rolls_back_and_continues -v
→ FAILED — AssertionError: assert 2 == 1
```
The orphaned Writeup (flushed but never matched with a WriteupUncensored) survived the outer commit, raising `Writeup.query.count()` to 2 instead of 1.

### sync.py unchanged

`git diff ctfd_censored_writeups/sync.py` is empty. sync.py was restored exactly after the ablation run. `git status` shows only `tests/test_sync.py` modified.

### Commit

`test: inject post-flush failure to genuinely cover savepoint isolation`

## Concerns / Notes
- The `SAWarning: Flushing object <Flags ...> with incompatible polymorphic identity 'static'` on `test_flag_in_censored_is_quarantined` is a CTFd 3.7.6 / SQLAlchemy 1.x warning from `gen_flag` itself (not from our code); it does not affect test correctness.
- `gen_flag` is imported directly in `test_sync.py` from `tests.helpers` (conftest.py sets up the path so this resolves to `.ctfd-src/tests/helpers.py`). `gen_flag` was not in conftest.py's import list but is available.
- The flag-scan only covers static flags; regex/dynamic flags cannot be detected without executing the CTFd flag-checker, which is intentionally out of scope here.
