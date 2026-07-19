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
    // core-beta registers Bootstrap Tab's delegated data-api listener on
    // document, which handles this dynamically injected button. The theme's
    // own tab buttons instead call Tab.show() via Alpine @click handlers,
    // but both paths share Tab's active/pane management.
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
