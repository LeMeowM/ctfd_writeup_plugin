// Minimal, dependency-free reader. Reads challenge id from data attribute.
async function loadList(challengeId) {
  const res = await fetch(`/api/v1/writeups/${challengeId}`, { credentials: "same-origin" });
  const { data } = await res.json();
  const idx = document.getElementById("wu-index");
  idx.innerHTML = "";
  data.forEach((it) => {
    const a = document.createElement("a");
    a.href = "#"; a.textContent = it.title;
    a.onclick = (e) => { e.preventDefault(); loadOne(it.challenge_id, it.id); };
    idx.appendChild(a); idx.appendChild(document.createElement("br"));
  });
  if (data.length) loadOne(data[0].challenge_id, data[0].id);
}
async function loadOne(challengeId, writeupId) {
  const res = await fetch(`/api/v1/writeups/${challengeId}/${writeupId}`, { credentials: "same-origin" });
  const { data } = await res.json();
  document.getElementById("wu-read").innerHTML = data.body; // server already gated+rendered
}
window.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("wu-root");
  if (root) loadList(root.dataset.challengeId);
});
