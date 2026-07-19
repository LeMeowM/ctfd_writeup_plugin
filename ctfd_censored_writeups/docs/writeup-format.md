# Writeup File Format

Each writeup is a Markdown file with a YAML frontmatter block followed by the writeup body.

## Frontmatter

The frontmatter block is delimited by `---` lines and must appear at the very start of the file (leading blank lines are ignored).

```yaml
---
challenge: "Web 101"     # required — challenge name or numeric ID
title: "My Approach"     # required — display title
author: "alice"          # optional
sort_order: 0            # optional, integer, default 0 (lower = shown first)
tags: [web, beginner]    # optional — YAML list or comma-separated string
language: "en"           # optional — e.g. "en", "fr"
visible: true            # optional, boolean, default true
---
```

### Field reference

| Field | Type | Default | Notes |
|---|---|---|---|
| `challenge` | string or int | (required) | See resolution rules below |
| `title` | string | `""` | Optional; stored as empty string if omitted |
| `author` | string | `null` | Displayed as attribution |
| `sort_order` | integer | `0` | Ascending; ties broken by insertion order |
| `tags` | list or comma-string | `[]` | Both `[web, beginner]` and `"web, beginner"` are accepted |
| `language` | string | `null` | Stored as-is; no validation |
| `visible` | boolean | `true` | `false` hides from all users without removing from DB |

### Challenge resolution (`challenge` field)

`compat.resolve_challenge_id` applies these rules in order:

1. If the value is a **string of digits** (e.g. `"42"` or bare integer `42`), it is treated as a **challenge ID**. The ID must exist in the challenges table; if it does not, the writeup is quarantined.
2. Otherwise it is matched **by name** against `Challenges.name`. Exactly one match is required; **zero or two-or-more matches both quarantine the writeup** (ambiguous-name rule).

A writeup with an unresolvable `challenge` field is stored in the database with `quarantined=True` and is never served to users.

## Redaction Markers

Redaction is applied to the body before storage. Two syntaxes are supported.

### Inline markers

```
The flag is <!--redact-->CTF{s3cr3t_flag_here}<!--/redact-->, found in the config file.
```

Everything between `<!--redact-->` and `<!--/redact-->` (inclusive) is replaced by:

```
〔redacted — solve this challenge to view〕
```

(This is the `PLACEHOLDER_INLINE` constant in `redaction.py`.)

### Fenced blocks

A fenced code block whose info string is exactly `flag` or `spoiler` is replaced entirely:

````markdown
Here is the exploit output:

```flag
CTF{s3cr3t_flag_here}
```

And here is the decompiled binary:
````

The entire `` ```flag `` ... `` ``` `` block is replaced by:

````
```
〔redacted — solve this challenge to view〕
```
````

(This is the `PLACEHOLDER_BLOCK` constant, which itself is a fenced code block containing the placeholder text.)

Both `flag` and `spoiler` info strings trigger this substitution.

### Fail-closed behavior

The redaction engine is deliberately fail-closed. Any malformed input marks the writeup as not-ok and causes it to be quarantined (never served):

- **Unclosed fence**: a `` ```flag `` or `` ```spoiler `` line with no matching closing `` ``` `` — the remainder of the document is replaced by `PLACEHOLDER_BLOCK` and `ok` is set to `False`.
- **Unclosed inline marker**: a `<!--redact-->` with no following `<!--/redact-->` — the remainder of the document from that point is replaced by `PLACEHOLDER_INLINE` and `ok` is set to `False`.
- **Nested inline markers**: a `<!--redact-->` appearing inside another unclosed `<!--redact-->` span is treated as unclosed (the outer opener matches the nearer closer, but if the next open comes before the close, the outer span is considered unclosed) — same fail-closed behaviour.

After inline processing, `verify_no_secret` scans the censored output for any remaining redaction markers. If any are found (e.g. a partial sub-string that slipped through), `ok` is set to `False`.

A quarantined writeup's censored body is stored in the DB but is never returned to users.

## Images

Host images externally (imgur, GitHub, a repo raw URL, …) and reference them
by URL:

```markdown
![exploit output](https://i.imgur.com/example.png)
```

Do **not** embed base64 `data:` URIs — they bloat the database and count
against the submission size cap.

**Images cannot be redacted.** The redaction engine works on text only; a
screenshot that shows the flag leaks it to non-solvers no matter what markers
surround it. Never screenshot the flag or the final solution output.
Reviewers check every image during submission review for exactly this reason.

## Source Key and File Identity

The **source key** is the repo-relative file path (e.g. `web/web101-myapproach.md`). It is the stable primary key for upsert logic:

- **Rename a file** = the old source key is deleted, the new source key is created as a fresh row.
- **Edit a file in-place** = same source key, the existing row is updated.
- **Delete a file** = the row is removed from both DB binds on the next sync.

## Complete Example File

````markdown
---
challenge: "Web 101"
title: "Server-Side Template Injection via the name parameter"
author: "alice"
sort_order: 1
tags: [web, ssti, python]
language: en
visible: true
---

## Overview

This challenge exposes a Flask endpoint that passes user input directly to `render_template_string`.

## Exploitation

Send the following payload in the `name` query parameter:

<!--redact-->{{config.SECRET_KEY}}<!--/redact-->

This works because the template context includes the Flask config object.

## Flag

```flag
CTF{s3cr3t_flag_here}
```

## Takeaways

Never pass user input to `render_template_string` without sanitization.
````
