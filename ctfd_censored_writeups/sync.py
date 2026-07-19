"""
Sync engine: walk *.md files under a directory, parse each, resolve its
challenge, and upsert Writeup (main DB) + WriteupUncensored (uncensored bind)
idempotently keyed by source_key (repo-relative path). Deletes rows whose
file vanished. Quarantines rows that fail to parse, resolve, or that leak a
flag into the censored body.
"""
import os
from dataclasses import dataclass, field
from CTFd.models import db
from .models import Writeup, WriteupUncensored
from .parser import parse_writeup_file
from .publish import censored_body_leaks_flag
from . import compat


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    quarantined: int = 0
    errors: list = field(default_factory=list)


def _iter_markdown(repo_path):
    for root, _dirs, files in os.walk(repo_path):
        for name in files:
            if name.endswith(".md"):
                full = os.path.join(root, name)
                yield os.path.relpath(full, repo_path), full


def sync_from_dir(app, repo_path: str) -> SyncReport:
    report = SyncReport()
    seen = set()

    for source_key, full in _iter_markdown(repo_path):
        seen.add(source_key)  # outside savepoint: a crashing file must not lose its existing row
        sp = db.session.begin_nested()
        try:
            text = open(full, encoding="utf-8").read()
            parsed = parse_writeup_file(text, source_key)
            challenge_id = compat.resolve_challenge_id(parsed.challenge_ref)

            # Flag scan: check whether any static flag value appears verbatim in
            # the censored body. This catches authors accidentally leaving the
            # flag outside a <!--redact-->…<!--/redact--> block.
            # NOTE: dynamic/regex flags are NOT detected; only static flag content
            # strings that appear as a literal substring are caught here.
            flag_leaked = False
            if parsed.ok and censored_body_leaks_flag(challenge_id, parsed.censored_body):
                flag_leaked = True
                report.errors.append(
                    f"{source_key}: censored body contains the challenge's static flag (redacted)"
                )

            quarantined = (not parsed.ok) or (challenge_id is None) or flag_leaked

            w = Writeup.query.filter_by(source_key=source_key).first()
            is_new = w is None
            if is_new:
                w = Writeup(source_key=source_key)
                db.session.add(w)

            # Build the new values dict and detect whether anything changed so
            # that a second identical sync run reports updated=0 (idempotent).
            new_vals = dict(
                challenge_id=challenge_id,
                title=parsed.title,
                author=parsed.author,
                censored_body=parsed.censored_body,
                sort_order=parsed.sort_order,
                tags=",".join(parsed.tags) if parsed.tags else None,
                language=parsed.language,
                visible=parsed.visible,
                quarantined=quarantined,
            )
            changed = is_new or any(getattr(w, k) != v for k, v in new_vals.items())
            for k, v in new_vals.items():
                setattr(w, k, v)
            db.session.flush()  # assign w.id if new

            u = WriteupUncensored.query.filter_by(writeup_id=w.id).first()
            if u is None:
                u = WriteupUncensored(writeup_id=w.id)
                db.session.add(u)
            if u.uncensored_body != parsed.uncensored_body:
                u.uncensored_body = parsed.uncensored_body
                changed = True

            if quarantined:
                report.quarantined += 1
            if is_new:
                report.created += 1
            elif changed:
                report.updated += 1

            sp.commit()
        except Exception as e:
            # Per-file safety net: one malformed file must not abort the whole sync.
            # Roll back this file's partial work so we don't persist a Writeup
            # without its matching WriteupUncensored (cross-bind inconsistency).
            sp.rollback()
            report.errors.append(f"{source_key}: {e}")

    # Deletion pass: rows whose file no longer exists are removed from both binds.
    for w in Writeup.query.all():
        if w.source_key not in seen:
            WriteupUncensored.query.filter_by(writeup_id=w.id).delete()
            db.session.delete(w)
            report.deleted += 1

    db.session.commit()
    return report
