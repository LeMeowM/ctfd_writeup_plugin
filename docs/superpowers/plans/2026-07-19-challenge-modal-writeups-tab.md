# Challenge Modal Writeups Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Writeups" tab to the CTFd challenge modal (alongside "Challenge" and "N Solves") that lists the challenge's writeups as links, injected client-side by a plugin script.

**Architecture:** A single new JS asset (`challenge-tab.js`) registered via CTFd's `register_plugin_script()` runs on every page. On the challenges page it observes the challenge modal container (`#challenge-window`, whose innerHTML core-beta re-renders on every modal open), injects a Bootstrap-5 tab button + pane, and populates the pane from the existing `GET /api/v1/writeups/<challenge_id>` endpoint. No server-side or API changes.

**Tech Stack:** CTFd 3.7.6, core-beta theme (Bootstrap 5 + Alpine.js), vanilla ES2019 JS, pytest.

**Spec:** `docs/superpowers/specs/2026-07-19-challenge-modal-writeups-tab-design.md`

## Global Constraints

- Fail silent: if `#challenge-window`, `.nav-tabs`, `.tab-content`, or `#challenge-id` is missing, or the API call fails, the modal must render exactly as stock (tab may stay with label "Writeups" and pane "No writeups yet" on API failure — see spec).
- All dynamic strings (titles, authors) rendered via `textContent`, never `innerHTML`.
- Tab is always injected (even with zero writeups); empty state text is exactly `No writeups yet`.
- Tab label is `Writeups`, updated to `Writeups (N)` after a successful non-empty fetch.
- Links open in a new browser tab: `target="_blank"` with `rel="noopener"`.
- Run tests with `.venv/bin/pytest` from the repo root (CTFd source is wired via `.ctfd-src` + `pytest.ini`; the plugin is symlinked into CTFd's plugins dir by `tests/conftest.py`).
- Commit messages end with `Co-Authored-By:` trailer per repo convention (see `git log`).

---

### Task 1: `challenge-tab.js` asset + script registration

**Files:**
- Create: `ctfd_censored_writeups/assets/challenge-tab.js`
- Modify: `ctfd_censored_writeups/__init__.py` (add one `register_plugin_script` call in `load()`)
- Test: `tests/test_challenge_tab.py` (new file)

**Interfaces:**
- Consumes: existing `GET /api/v1/writeups/<challenge_id>` (returns `{"success": true, "data": [{"id", "challenge_id", "title", "author", "tags", "sort_order", "unlocked"}]}`); existing asset route prefix `/plugins/ctfd_censored_writeups/assets/` (already registered via `register_plugin_assets_directory`).
- Produces: script URL `/plugins/ctfd_censored_writeups/assets/challenge-tab.js` registered in `app.plugin_scripts` (rendered into every page by base.html's `{{ Plugins.scripts }}`). Task 2's docs and Task 3's verification refer to this URL and to the DOM ids `#writeups` (pane) and class `challenge-writeups` (tab button).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_challenge_tab.py`:

```python
SCRIPT_URL = "/plugins/ctfd_censored_writeups/assets/challenge-tab.js"


def test_challenge_tab_script_registered(app):
    # register_plugin_script() appends to app.plugin_scripts, which base.html
    # renders into every page via {{ Plugins.scripts }}.
    with app.app_context():
        from CTFd.utils.plugins import get_registered_scripts
        assert SCRIPT_URL in get_registered_scripts()


def test_challenge_tab_script_in_page_html(app):
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert SCRIPT_URL.encode() in r.data


def test_challenge_tab_asset_served(app):
    client = app.test_client()
    r = client.get(SCRIPT_URL)
    assert r.status_code == 200
    # sanity: it is our script, not an error page
    assert b"challenge-window" in r.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_challenge_tab.py -v`
Expected: 3 FAILED — `test_challenge_tab_script_registered` with `AssertionError` (URL not in list), `test_challenge_tab_script_in_page_html` with `AssertionError`, `test_challenge_tab_asset_served` with `assert 404 == 200`.

- [ ] **Step 3: Create the JS asset**

Create `ctfd_censored_writeups/assets/challenge-tab.js` with exactly:

```js
// Injects a "Writeups" tab into the core-beta challenge modal.
// Fail-silent: on themes without the expected markup this does nothing.
(() => {
  "use strict";

  async function injectTab(container) {
    if (container.querySelector("#writeups")) return; // already injected for this render
    const idInput = container.querySelector("#challenge-id");
    const navTabs = container.querySelector(".nav-tabs");
    const tabContent = container.querySelector(".tab-content");
    if (!idInput || !navTabs || !tabContent) return;
    const challengeId = parseInt(idInput.value, 10);
    if (!Number.isFinite(challengeId)) return;

    const li = document.createElement("li");
    li.className = "nav-item";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "nav-link challenge-writeups";
    // core-beta imports Bootstrap's Tab component, whose delegated data-api
    // listener on document handles dynamically added [data-bs-toggle="tab"]
    // buttons — the theme's own tabs use the same machinery (Tab.show()).
    btn.setAttribute("data-bs-toggle", "tab");
    btn.setAttribute("data-bs-target", "#writeups");
    btn.textContent = "Writeups";
    li.appendChild(btn);
    navTabs.appendChild(li);

    const pane = document.createElement("div");
    pane.id = "writeups";
    pane.className = "tab-pane fade";
    pane.setAttribute("role", "tabpanel");
    tabContent.appendChild(pane);

    const showEmpty = () => {
      const p = document.createElement("p");
      p.className = "text-center text-muted pt-4";
      p.textContent = "No writeups yet";
      pane.replaceChildren(p);
    };

    let entries;
    try {
      const res = await fetch(`/api/v1/writeups/${challengeId}`, {
        credentials: "same-origin",
      });
      if (!res.ok) return showEmpty();
      const body = await res.json();
      entries = body && body.data;
    } catch (_e) {
      return showEmpty();
    }
    if (!Array.isArray(entries) || entries.length === 0) return showEmpty();

    btn.textContent = `Writeups (${entries.length})`;
    const list = document.createElement("ul");
    list.className = "list-unstyled pt-4";
    for (const w of entries) {
      const item = document.createElement("li");
      item.className = "pb-2 text-center";
      if (!w.unlocked) {
        const lock = document.createElement("i");
        lock.className = "fas fa-lock pe-2";
        lock.title = "Solve to view the full writeup";
        item.appendChild(lock);
      }
      const a = document.createElement("a");
      a.href = `/writeups/${challengeId}/${w.id}`;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = w.title || "(untitled)";
      item.appendChild(a);
      if (w.author) {
        const author = document.createElement("small");
        author.className = "text-muted ps-2";
        author.textContent = `by ${w.author}`;
        item.appendChild(author);
      }
      list.appendChild(item);
    }
    pane.replaceChildren(list);
  }

  function start() {
    // core-beta's challenges page hosts the modal here and re-renders its
    // innerHTML (x-html) each time a challenge is opened.
    const container = document.getElementById("challenge-window");
    if (!container) return;
    const observer = new MutationObserver(() => {
      if (container.querySelector("#challenge-id")) injectTab(container);
    });
    observer.observe(container, { childList: true, subtree: true });
  }

  if (document.readyState !== "loading") start();
  else document.addEventListener("DOMContentLoaded", start);
})();
```

- [ ] **Step 4: Register the script in the plugin loader**

In `ctfd_censored_writeups/__init__.py`, change:

```python
    from CTFd.plugins import register_plugin_assets_directory, register_user_page_menu_bar
    register_plugin_assets_directory(app, base_path="/plugins/ctfd_censored_writeups/assets/")
    register_user_page_menu_bar("Writeups", "/writeups")
```

to:

```python
    from CTFd.plugins import (
        register_plugin_assets_directory,
        register_plugin_script,
        register_user_page_menu_bar,
    )
    register_plugin_assets_directory(app, base_path="/plugins/ctfd_censored_writeups/assets/")
    register_plugin_script("/plugins/ctfd_censored_writeups/assets/challenge-tab.js")
    register_user_page_menu_bar("Writeups", "/writeups")
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `.venv/bin/pytest tests/test_challenge_tab.py -v`
Expected: 3 passed.

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `.venv/bin/pytest -q`
Expected: all tests pass (baseline before this change: whole suite green).

- [ ] **Step 7: Commit**

```bash
git add ctfd_censored_writeups/assets/challenge-tab.js ctfd_censored_writeups/__init__.py tests/test_challenge_tab.py
git commit -m "feat: Writeups tab in challenge modal via injected script

Registers challenge-tab.js on every page; on the challenges page it
observes #challenge-window, injects a Bootstrap tab + pane per modal
render, and lists writeup links from /api/v1/writeups/<id>. Fail-silent
on themes without the expected markup; titles/authors rendered via
textContent.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Documentation

**Files:**
- Modify: `docs/how-it-works.md` (new section between "HTML Routes" and "Known Limitations", i.e. after the "HTML Routes" section body)
- Modify: `docs/operator-setup.md` (new section after "## Admin Page" at end of file)
- Modify: `README.md` (one bullet in "What It Does")

**Interfaces:**
- Consumes: script URL `/plugins/ctfd_censored_writeups/assets/challenge-tab.js` and behavior implemented in Task 1.
- Produces: nothing consumed by other tasks.

- [ ] **Step 1: Add the how-it-works section**

In `docs/how-it-works.md`, insert immediately before the `## Known Limitations` heading:

```markdown
## Challenge Modal Tab

The plugin adds a "Writeups" tab to the challenge modal on the challenges page, next to the built-in "Challenge" and "N Solves" tabs.

**Mechanism**: `challenge-tab.js` is registered via CTFd's `register_plugin_script()`, so it loads on every page (no theme template is overridden). On the challenges page, the core-beta theme re-renders the modal's inner HTML into `#challenge-window` each time a challenge is opened; the script observes that container with a `MutationObserver` and injects, per render, a Bootstrap tab button (`data-bs-toggle="tab"`) and a pane (`#writeups`).

**Content**: the pane fetches `GET /api/v1/writeups/<challenge_id>` and lists each visible writeup as a link to its `/writeups/<challenge_id>/<writeup_id>` page (opened in a new browser tab), with the author and a lock icon on entries the viewer has not unlocked. The tab label becomes "Writeups (N)". With zero writeups — or if the API call fails — the pane reads "No writeups yet". Titles and authors are rendered with `textContent`, so writeup metadata cannot inject HTML.

**Theme dependency (fail-silent)**: the injection requires the core-beta modal markup (`#challenge-window`, `.nav-tabs`, `.tab-content`, `#challenge-id`). On a theme where any of these is absent, the script does nothing and the modal renders exactly as stock. The solve gate is unaffected either way: the tab only shows metadata the list API already exposes, and the linked pages enforce censoring server-side.
```

- [ ] **Step 2: Add the operator-setup note**

Append to the end of `docs/operator-setup.md` (after the "## Admin Page" section):

```markdown
## Challenge Modal Writeups Tab

No configuration is required. The plugin injects a "Writeups" tab into the challenge modal via a registered page script (`challenge-tab.js`). This targets the **core-beta** theme's modal markup; on other themes the script silently does nothing and the modal is unchanged. See [how-it-works.md](how-it-works.md#challenge-modal-tab) for the mechanism.
```

- [ ] **Step 3: Add the README bullet**

In `README.md`, in the "What It Does" list, insert after the "**Solve gate**" bullet:

```markdown
- **Challenge modal tab**: a "Writeups" tab appears in the challenge modal (core-beta theme), listing each writeup with a lock icon until solved. Injected client-side; silently absent on other themes.
```

- [ ] **Step 4: Verify docs render sanely and commit**

Run: `grep -n "Challenge Modal" docs/how-it-works.md docs/operator-setup.md README.md`
Expected: one hit in each of `docs/how-it-works.md` and `docs/operator-setup.md`; README hit shows the new bullet (grep for "Challenge modal tab" if casing differs).

```bash
git add docs/how-it-works.md docs/operator-setup.md README.md
git commit -m "docs: document the challenge modal Writeups tab

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: End-to-end verification on the dev instance

**Files:**
- No file changes (verification only; fixes loop back into Task 1's files if needed).

**Interfaces:**
- Consumes: `.dev/run.sh` + seeded dev instance (accounts `player`/`password`, `admin`/`password`; challenge "Web 101" has 2 writeups, "Crypto Warmup" has none); script + markup from Task 1.

- [ ] **Step 1: Start the dev instance**

Run from the repo root: `.dev/run.sh 4000` (background it). Wait until `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4000/` prints `200`.

- [ ] **Step 2: Programmatic smoke checks**

```bash
# script tag present on a rendered page
curl -s http://127.0.0.1:4000/ | grep -c "challenge-tab.js"
# asset serves
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4000/plugins/ctfd_censored_writeups/assets/challenge-tab.js
```

Expected: first command prints `1` (or more); second prints `200`.

- [ ] **Step 3: Human browser checklist**

Ask the user to verify at `http://127.0.0.1:4000` (this is browser-side behavior a curl cannot exercise):

1. Log in as `player` / `password`, open **Web 101** on `/challenges` → modal shows a third tab "Writeups (2)"; both entries have lock icons; clicking the tab switches panes, and clicking back to "Challenge"/"Solves" works.
2. Click a writeup link → opens `/writeups/1/<id>` in a new browser tab showing the censored body.
3. Open **Crypto Warmup** → tab reads "Writeups" and the pane shows "No writeups yet".
4. Solve **Web 101** (flag `CTF{ssti_is_fun}`) if not already solved, close and re-open the modal → lock icons gone; links show the uncensored body.
5. Log in as `admin` / `password`, open **Web 101** → no lock icons (admin preview).

- [ ] **Step 4: Record the outcome**

If any check fails, fix in Task 1's files, re-run `.venv/bin/pytest -q`, and repeat this task. When all checks pass, report completion (no commit needed unless fixes were made).
