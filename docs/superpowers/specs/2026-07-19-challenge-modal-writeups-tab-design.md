# Challenge Modal Writeups Tab — Design

**Date:** 2026-07-19
**Status:** Approved

## Goal

Add a "Writeups" tab to the CTFd challenge modal, alongside the built-in "Challenge" and "N Solves" tabs, so players can reach a challenge's writeups without leaving the challenges page.

## Context

In CTFd 3.7.6 with the core-beta theme, the challenge modal's inner HTML — including the tab bar — is rendered server-side by `GET /api/v1/challenges/<id>` from the theme's `challenge.html` template and swapped into the modal each time a challenge is opened. Two plugin hooks could add a tab:

- `override_template("challenge.html", …)` — the official pattern, but it requires shipping a pinned copy of the 228-line core-beta template, and the override is theme-blind: on any other theme it replaces the whole modal with core-beta markup (hard failure).
- `register_plugin_script(…)` — inject a script into every page that adds the tab client-side (chosen; fails soft on unknown themes).

## Decisions

| Decision | Choice |
|---|---|
| Mechanism | Client-side injection via `register_plugin_script` |
| Tab content | List of writeup title links opening the existing `/writeups/<challenge_id>/<writeup_id>` pages in a new browser tab |
| Empty state | Tab always shown; body reads "No writeups yet" when the challenge has no visible writeups |
| Locked entries | Listed with a lock icon (metadata only; links still work and serve the censored page) |
| Tab label | "Writeups", updated to "Writeups (N)" once the list is fetched |
| Unknown theme / API error | Fail silent: no tab, modal untouched |

## Component

One new file: `ctfd_censored_writeups/assets/challenge-tab.js`, registered in the plugin's `load()` with:

```python
register_plugin_script("/plugins/ctfd_censored_writeups/assets/challenge-tab.js")
```

The assets directory is already served at that path via `register_plugin_assets_directory`. There are no server-side changes: the tab consumes the existing `GET /api/v1/writeups/<challenge_id>` list endpoint, which already returns `id`, `challenge_id`, `title`, `author`, `tags`, `sort_order`, and `unlocked` for each visible, non-quarantined writeup.

## Behavior

1. **Detect modal render.** The script runs on every page (that is how `register_plugin_script` works) but only acts when it finds the challenge modal container. A MutationObserver scoped to that container fires each time CTFd swaps in a freshly rendered modal body — injection therefore re-runs naturally on every modal open, with no stale state from the previous challenge.
2. **Read the challenge ID** from the `#challenge-id` hidden input already present in the rendered modal.
3. **Inject markup.** Append to the modal's `.nav-tabs` a `<li class="nav-item">` containing a "Writeups" `<button class="nav-link" data-bs-toggle="tab" data-bs-target="#writeups">`, and append a matching `<div class="tab-pane fade" id="writeups">` to `.tab-content`. Bootstrap 5's stock tab machinery — the same one the theme's own tabs use — handles switching and sibling deactivation; no custom switching logic.
4. **Fetch and render.** Fetch `/api/v1/writeups/<id>` with same-origin credentials. On success, render into the pane:
   - One entry per writeup, in API order (the API already sorts by `sort_order`): the title as an `<a>` to `/writeups/<challenge_id>/<writeup_id>` with `target="_blank"` and `rel="noopener"`, the author as muted text, and a lock icon when `unlocked` is false.
   - Update the tab button text to "Writeups (N)".
   - If the list is empty, render "No writeups yet".
   - All dynamic strings (titles, authors) are set via `textContent`, never `innerHTML`, so a hostile writeup title cannot inject HTML.
5. **Idempotence guard.** Before injecting, skip if a `#writeups` pane already exists in the current modal body (protects against duplicate observer callbacks for the same render).

## Failure Modes

Fail-silent by design, mirroring the plugin's fail-closed philosophy:

- Modal container, `.nav-tabs`, `.tab-content`, or `#challenge-id` not found (custom theme, future theme change) → do nothing; the modal renders exactly as stock.
- API call fails, returns non-200, or returns malformed JSON → the already-injected tab stays, its label stays "Writeups" (no count), and the pane renders "No writeups yet"; nothing is surfaced to the user.
- The solve gate is unaffected: the tab only displays metadata the list API already exposes to that user, and the linked pages enforce censoring server-side as before.

## Documentation

- `docs/how-it-works.md`: new "Challenge modal tab" section — mechanism (script injection, no template override), what it renders, and the fail-silent theme dependency.
- `docs/operator-setup.md`: note that the tab targets the core-beta theme's modal markup and silently no-ops on themes where the expected structure is absent; no configuration required.
- `README.md`: one line in "What It Does".

## Testing

- **Python (pytest):** the base page HTML includes the `challenge-tab.js` script tag after plugin load; `GET /plugins/ctfd_censored_writeups/assets/challenge-tab.js` returns 200.
- **Manual (dev instance, `.dev/run.sh`):** as `player`, open Web 101 → tab shows "Writeups (2)" with lock icons; solve → icons gone, links open full writeups; Crypto Warmup → "No writeups yet"; admin sees all writeups unlocked.

## Out of Scope

- Rendering writeup bodies inside the modal (list links out instead).
- Supporting themes other than core-beta (graceful no-op only).
- Any server-side or API changes.
