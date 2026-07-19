"""
Publish pipeline for player submissions.

A submission is composed into a canonical frontmatter document and pushed
through the SAME parse -> redaction -> flag-scan path as file sync, so there
is exactly one fail-closed pipeline to audit. Published rows use the
`submission://<id>` source-key namespace, which file paths can never collide
with; sync's deletion pass skips that namespace.
"""
from dataclasses import dataclass, field

import yaml

from .parser import parse_writeup_file, ParsedWriteup
from . import compat

SUBMISSION_PREFIX = "submission://"

WARN_MALFORMED = "redaction markers are malformed (fail-closed)"
WARN_FLAG_LEAK = "censored body still contains a static flag"


def source_key_for(sub_id: int) -> str:
    return f"{SUBMISSION_PREFIX}{sub_id}"


def compose_document(challenge_id: int, title: str, author: str | None, body: str) -> str:
    # challenge as a digit-string resolves by ID (never ambiguous-name quarantine).
    fm = {"challenge": str(challenge_id), "title": title}
    if author:
        fm["author"] = author
    fm_text = yaml.safe_dump(fm, default_flow_style=False, allow_unicode=True)
    return f"---\n{fm_text}---\n\n{body}"


def censored_body_leaks_flag(challenge_id, censored_body) -> bool:
    """Shared with sync: does any static flag appear verbatim in the censored
    output? Dynamic/regex flags are NOT detected (same limitation as sync)."""
    if challenge_id is None or not censored_body:
        return False
    for flag_val in compat.static_flag_values(challenge_id):
        if flag_val and flag_val in censored_body:
            return True
    return False


@dataclass
class Evaluation:
    parsed: ParsedWriteup
    warnings: list = field(default_factory=list)


def evaluate(challenge_id: int, body: str) -> Evaluation:
    """Run a submission body through the real pipeline and report blockers.

    Title/author don't affect redaction, so a placeholder title is used; the
    real publish re-parses with the submission's actual fields.
    """
    doc = compose_document(challenge_id, "preview", None, body)
    parsed = parse_writeup_file(doc, "submission://preview")
    warnings = []
    if not parsed.ok:
        warnings.append(WARN_MALFORMED)
    if censored_body_leaks_flag(challenge_id, parsed.censored_body):
        warnings.append(WARN_FLAG_LEAK)
    return Evaluation(parsed=parsed, warnings=warnings)
