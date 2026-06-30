# CTFd Censored-Writeups Plugin — Design

**Status:** Approved (brainstorming) — ready for implementation planning
**Date:** 2026-06-30
**Target:** CTFd latest 3.7.x (exact patch release confirmed at setup)
**Companion:** `impl_details.txt` (original design rationale; this doc pins the open decisions)

---

## 0. The one invariant

**Uncensored bytes must never leave the server for a request that has not passed the solve check.**

Enforced server-side only. For an unsolved challenge, every HTTP response — HTML *and* JSON *and* error pages — contains only censored content; the flag and solve script are physically absent from the bytes on the wire. The check is re-evaluated on every request; no client-supplied or cached "solved" decision is trusted.

Defense-in-depth backing this: the unsolved code path obtains a DB handle for censored data only and **never opens the uncensored bind**, so a query bug in that path cannot reach secrets.

---

## 1. Locked-in decisions

| Area | Decision |
|---|---|
| Data source | External **git repo of markdown**, synced in. Plugin is read-mostly; the repo is the source of truth, CTFd tables are a cache. |
| Censoring model | **Derived** — one source file per writeup; redaction markers are mechanically stripped to produce the censored body. |
| Storage | **Defense-in-depth.** Censored bodies + metadata in CTFd's main DB; uncensored bodies in a separate SQLAlchemy bind (`__bind_key__="uncensored"`) the unsolved path never opens. |
| Target version | CTFd **latest 3.7.x**. Gate logic isolated behind a thin compat shim so re-pinning is cheap. |
| Post-CTF policy | **Config toggle**, default = keep the gate. Flip to open all writeups uncensored once the event ends. |
| Front-end | **Self-contained plugin page** (index pane + reading pane) + one nav-link injection into the theme. |
| Sync trigger | **Git webhook** (HMAC-verified) as primary; **manual admin button + CLI command** as fallback for initial seed and re-syncs. |
| Challenge mapping | Frontmatter `challenge:` — if numeric, treat as CTFd `challenge_id`; otherwise match against `Challenges.name`. |
| Documentation | Ship end-user/admin docs: writeup file structure + how the plugin works (see §8). |

---

## 2. Architecture & components

Five units, each with one purpose, a defined interface, and independent tests.

### 2.1 `redaction` (pure, safety-critical)
Pure function: markdown source → censored markdown. No I/O, no DB. Heaviest test coverage.

- **Inline span:** `<!--redact-->secret<!--/redact-->` → replaced by a visible placeholder `〔redacted — solve this challenge to view〕`.
- **Fenced block:** a ```` ```flag ```` or ```` ```spoiler ```` fenced code block has its entire contents stripped (this is where the solve script lives) and replaced by a placeholder block.
- Malformed/nested/unclosed markers fail **closed** (treat the remainder as redacted rather than leaking).
- After producing the censored body, assert no redacted span survived (verification step, §6).

### 2.2 `gate` (pure-ish)
`(current_user, challenge_id) → CENSORED | UNCENSORED`. No rendering, no routing. Mode-aware, admin-aware, post-CTF-aware. See §4.

### 2.3 `models`
- `Writeup` (main DB): `id`, `challenge_id` (resolved), `source_key` (stable id = repo-relative path or frontmatter `id`), `title`, `author`, `censored_body`, `sort_order`, `tags`, `language`, `visible`, `quarantined`, `created_at`, `updated_at`.
- `WriteupUncensored` (`__bind_key__="uncensored"`): `writeup_id`, `uncensored_body`. Related by id in app code — **no cross-bind FK**; integrity enforced in application code.

### 2.4 `sync`
Clones/pulls the repo, walks markdown files, parses frontmatter + body, calls `redaction`, upserts rows idempotently keyed by `source_key`.

- **Challenge resolution:** `challenge:` numeric → `challenge_id`; else match `Challenges.name`. No/ambiguous match → row stored but `quarantined=true` (never served).
- **Deletes:** file removed from repo → corresponding rows (both binds) removed.
- **Orphans:** challenge deleted while writeups exist → rows quarantined, not served.
- Idempotent: re-running over unchanged repo state is a no-op.

### 2.5 `views` (blueprint)
All content paths route through `gate`. Registered in `load(app)` with `register_plugin_assets_directory`; both binds materialized via `create_all()` on startup.

---

## 3. Repo / writeup file format

Per writeup, a markdown file with YAML frontmatter:

```yaml
---
challenge: 42          # numeric → challenge_id; non-numeric → match Challenges.name
title: "Unintended RSA solve"
author: "alice"        # display label (not a CTFd user FK)
sort_order: 10         # optional; explicit ordering within a challenge
tags: [crypto, rsa]    # optional
language: en           # optional
visible: true          # optional, default true
---
```

Body is markdown with redaction markers:

```markdown
We recovered the private key, then:

```flag
# entire contents of this fenced block are stripped in the censored view
python3 solve.py --target $HOST    # the actual solve script
FLAG{...}
```

The intended path was <!--redact-->the LSB oracle<!--/redact-->, which leaks one bit per query.
```

`source_key` (stable identity for idempotent sync) = repo-relative file path, or an explicit `id:` frontmatter field if present.

---

## 4. The gate (pinned to 3.7.x; isolated behind compat shim)

1. `CTFd.utils.user.get_current_user()`.
2. Resolve account for current mode (`is_teams_mode()` / `get_model()`); **guard team-mode user with no team** (returns CENSORED, never crashes).
3. `Solves` existence on `(account_id, challenge_id)` ⇒ solved ⇒ UNCENSORED.
4. **Admin bypass:** `user.type == "admin"` ⇒ always UNCENSORED (author preview).
5. **Post-CTF toggle:** event ended AND toggle = open ⇒ UNCENSORED for all.

Decorators: `@authed_only`; challenge-visibility check (respects hidden/locked/unreleased challenges). **Not** `@during_ctf_time_only` — writeups remain readable after the event ends.

> Version caveat: confirm `account_id`, `get_model`, `is_teams_mode`, `Solves` columns against the pinned 3.7.x `CTFd/models` + `CTFd/utils/user` before relying on them. The compat shim is the only place these names appear.

---

## 5. Routes & API

- `GET /writeups/<challenge_id>` — **list/index**: titles + metadata of every visible, non-quarantined writeup, always returned (the list is not secret). Each entry carries a censored/unlocked badge for this requester.
- `GET /writeups/<challenge_id>/<writeup_id>` — **single**, gated. **IDOR discipline:** load the writeup, take its `challenge_id` **from the row**, run the gate against *that* challenge, then choose body. Never trust the URL's `challenge_id`.
- `GET /api/v1/writeups/<challenge_id>[/<writeup_id>]` — JSON, same gate. Unsolved → censored only.
- `POST /writeups/_webhook` — HMAC-signature-verified; triggers `sync`; returns fast; rejects bad/missing signatures.
- Admin page (`@admins_only`) — "Sync now" button + last-sync status/quarantine report. Mirrored by a `flask` CLI command (`flask writeups sync`) for scripts and the initial seed.

---

## 6. Error handling & leakage defenses

- Server-side gate only; no CSS/JS hiding.
- API payloads obey the gate, not just HTML.
- Gated responses: `Cache-Control: private, no-store`; no shared/proxy cache may serve an uncensored response to another user. Rendered HTML may be cached **server-side** keyed by `writeup_id`, but delivery is always gated — never a cacheable HTTP response keyed only by URL.
- **Redaction verification:** before storing, assert no redacted span survived in the censored body.
- **Flag scan (belt-and-suspenders):** scan the censored body for the challenge's known flag(s); warn/quarantine if found. Note the limitation for regex/dynamic flags to authors.
- Never run the live instance in Flask debug mode. 4xx/5xx and stack traces must never contain uncensored bytes.
- No uncensored bodies or flags logged to files less protected than the uncensored bind.
- Challenge visibility respected for the censored list too (no writeups for unreleased/hidden challenges).

---

## 7. CTF lifecycle

- **During CTF:** unsolved → censored, solved → uncensored.
- **After CTF:** governed by the config toggle (default keep gate; optional open-all).
- **Before/paused:** writeups for unreleased challenges are unreachable.

---

## 8. Documentation deliverable

Ship `docs/` (in-repo, and surfaced on the admin page) covering:

1. **Writeup file structure** — frontmatter schema (every field, required/optional, defaults), the `challenge:` id-then-name resolution rule, redaction marker syntax (inline + fenced block) with examples, and how `source_key`/file path determines identity.
2. **How the plugin works** — the solve gate (user vs team mode, admin bypass, post-CTF toggle), the two-bind storage model and what it protects, the sync flow (webhook + manual + CLI), quarantine behavior (bad challenge mapping, orphans), and the leakage invariant authors must respect.
3. **Operator setup** — configuring the uncensored bind, the webhook secret, the post-CTF toggle, and running the initial seed.

---

## 9. Edge cases

Empty challenge (no writeups); challenge deleted with live writeups (orphan → quarantine); multiple/dynamic/regex flags vs the censored scan; team mode teammate-unlock + user-with-no-team; admin preview; long writeups/images/attachments (decide allowed set; ensure attachments can't leak the flag); stable `sort_order`; `visible=false` hidden from players, shown to admins; webhook replay/bad-signature.

---

## 10. Testing strategy

- **Gate matrix:** {unsolved, solved} × {user mode, team mode} × {player, admin} × {CTF running, CTF ended}; assert censored/uncensored per cell.
- **Leak assertion (primary):** for every unsolved/non-admin response — HTML, JSON, error — assert flag string and solve-script content **absent** from response bytes. Run against list, single, API, and error paths.
- **IDOR:** request writeup of challenge A with creds that solved only B → censored.
- **Redaction units:** markers stripped; nested/malformed/unclosed markers fail closed.
- **Sync:** idempotency; delete propagation; orphan/quarantine; id-then-name resolution incl. ambiguous-name handling.
- **Mode:** no crash for team-mode user with no team; correct user-mode behavior.
- **Webhook:** valid signature syncs; bad/missing signature rejected.

---

## 11. Build order

1. `models` + `load(app)` + both-bind `create_all()` on pinned 3.7.x.
2. `redaction` pure function + its tests.
3. `gate` single function (mode/admin/post-CTF aware) + leak/matrix tests before any UI.
4. `sync` (parse, resolve, upsert, delete, quarantine) + CLI command + tests.
5. Single-writeup route (gated, IDOR-safe) → list route → self-contained browsing page + nav link.
6. Webhook endpoint (HMAC) + admin sync page.
7. Documentation (§8).
8. Caching, post-CTF toggle wiring, optional live-uncensor polling.
9. Re-run full matrix; walk §6 checklist line by line.

---

### Note on the reference plugin
`lapchynski/ctfd-writeups` is useful for *how a writeup plugin wires into CTFd*, but solves the opposite problem (participant-submitted + points), has no censoring, is team-mode-buggy in user mode, and targets 2020-era CTFd. Mine for patterns; do not fork.
