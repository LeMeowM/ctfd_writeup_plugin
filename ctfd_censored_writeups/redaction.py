import re
from dataclasses import dataclass

PLACEHOLDER_INLINE = "〔redacted — solve this challenge to view〕"
PLACEHOLDER_BLOCK = "```\n〔redacted — solve this challenge to view〕\n```"

_OPEN = "<!--redact-->"
_CLOSE = "<!--/redact-->"
# Fenced block whose info string STARTS WITH `flag` or `spoiler` (word boundary:
# the token must be the first word, optionally followed by more text after a space).
# This catches ``flag bash``, ``spoiler python3``, etc. — fail-closed.
_FENCE = re.compile(r"^```(?:flag|spoiler)(?:\s.*)?$.*?^```\s*$", re.DOTALL | re.MULTILINE)
# Bare opener line — used to detect unclosed fences.
_FENCE_OPEN = re.compile(r"^```(?:flag|spoiler)(?:\s.*)?$", re.MULTILINE)


@dataclass
class CensorResult:
    censored: str
    redacted_spans: int
    ok: bool


def censor(markdown: str) -> CensorResult:
    ok = True
    spans = 0

    # 1) Fenced flag/spoiler blocks -> placeholder block.
    def _fence_sub(_m):
        nonlocal spans
        spans += 1
        return PLACEHOLDER_BLOCK

    text = _FENCE.sub(_fence_sub, markdown)

    # 1b) Detect any remaining bare opener (unclosed fence) — fail closed.
    m = _FENCE_OPEN.search(text)
    if m:
        text = text[:m.start()] + PLACEHOLDER_BLOCK
        spans += 1
        ok = False

    # 2) Inline redact spans. Walk manually to fail closed on malformed input.
    out = []
    i = 0
    n = len(text)
    while i < n:
        start = text.find(_OPEN, i)
        if start == -1:
            out.append(text[i:])
            break
        out.append(text[i:start])
        # find matching close AFTER the open; reject nesting (another open first).
        close = text.find(_CLOSE, start + len(_OPEN))
        next_open = text.find(_OPEN, start + len(_OPEN))
        if close == -1 or (next_open != -1 and next_open < close):
            # Unclosed or nested: redact from here to end, mark not-ok.
            out.append(PLACEHOLDER_INLINE)
            spans += 1
            ok = False
            i = n
            break
        out.append(PLACEHOLDER_INLINE)
        spans += 1
        i = close + len(_CLOSE)

    censored = "".join(out)
    if not verify_no_secret(censored):
        ok = False
    return CensorResult(censored=censored, redacted_spans=spans, ok=ok)


def verify_no_secret(censored: str) -> bool:
    return (_OPEN not in censored and _CLOSE not in censored
            and not _FENCE.search(censored)
            and not _FENCE_OPEN.search(censored))
