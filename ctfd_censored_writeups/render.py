"""
Markdown rendering hardened against stored XSS.

CTFd's markdown() renders with CMARK_OPT_UNSAFE, passing raw HTML (including
<script> and event-handler attributes) straight through. Writeup bodies now
include untrusted player submissions, so every rendered writeup/submission
body is sanitized with a UGC allowlist before it reaches a template's
`| safe` or a JS innerHTML sink. Applied to all writeup bodies (git-sourced
included) so there is a single audited render path, not an origin-branch that
a future sink could forget.
"""
from CTFd.utils import markdown as _markdown
from pybluemonday import UGCPolicy

_policy = UGCPolicy()


def render_markdown(md):
    return _policy.sanitize(_markdown(md or ""))
