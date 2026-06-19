/* ════════════════════════════════════════════════════════════════
   OpenTabs — Just Raised page
   Reads ./funding.json (written by opentabs.py's funding radar) and
   renders a feed of recent raises + the design roles each is hiring for.
   Separate from the job board (index.html) on purpose: this page is
   funding NEWS for research/outreach, not postings to apply to.
   ════════════════════════════════════════════════════════════════ */

const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// share the theme chosen on the job board
const theme = localStorage.getItem("theme") || "dark";
document.documentElement.setAttribute("data-theme",
  ["dark", "paper", "blush", "mint", "cream"].includes(theme) ? theme : "dark");

function ago(when) {
  const d = (Date.now() - new Date(when).getTime()) / 1000;
  if (isNaN(d)) return "recently";
  if (d < 3600)  return Math.max(1, Math.floor(d / 60)) + "m ago";
  if (d < 86400) return Math.floor(d / 3600) + "h ago";
  return Math.floor(d / 86400) + "d ago";
}

function cardHTML(f, n) {
  const idx   = String(n).padStart(2, "0");
  const tier1 = (f.priority || 0) >= 8;
  const roles = (f.roles || []).map((r) =>
    `<a class="role" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}` +
    (r.location ? `<span class="role-loc"> · ${esc(r.location)}</span>` : "") + `</a>`).join("");
  return `<article class="raise">
      <div class="raise-top">
        <span class="idx">${idx}</span>
        <span class="amt">${esc(f.amount || "Undisclosed")}</span>
        ${tier1 ? '<span class="badge t1">Tier-1 VC</span>' : ""}
        <span class="src">${esc(f.source || "")} · ${ago(f.first_seen)}</span>
      </div>
      <a class="raise-co" href="${esc(f.url || "#")}" target="_blank" rel="noopener">${esc(f.company)}</a>
      <div class="raise-meta">${esc(f.stage || "—")}<span class="sep">/</span>${esc(f.investors || "—")}</div>
      ${roles ? `<div class="roles"><span class="roles-lbl">Open design roles</span>${roles}</div>`
              : `<div class="roles none">No design roles posted yet — DM the founder.</div>`}
      ${f.url ? `<a class="read" href="${esc(f.url)}" target="_blank" rel="noopener">Read article →</a>` : ""}
    </article>`;
}

function render(data) {
  const live = (Array.isArray(data) ? data : [])
    .filter((f) => f.status !== "dismissed")
    .sort((a, b) => (b.first_seen || "").localeCompare(a.first_seen || ""));

  $("#raisedCount").textContent = live.length;
  $("#statRaises").textContent  = live.length;
  $("#statRaises2").textContent = live.length;
  $("#status").textContent = live.length
    ? "Updated " + new Date().toLocaleTimeString()
    : "No data yet";

  const feed = $("#feed");
  if (!live.length) {
    feed.innerHTML = '<div class="feed-empty">No raises tracked yet. ' +
      'The funding radar seeds this on its first scan.</div>';
    return;
  }
  feed.innerHTML = live.map((f, i) => cardHTML(f, i + 1)).join("");
}

function load() {
  fetch("./funding.json?_=" + Date.now())
    .then((r) => (r.ok ? r.json() : []))
    .then(render)
    .catch(() => { $("#status").textContent = "No data yet"; $("#empty").textContent = "Couldn't load funding data."; });
}

/* ── Column / List view toggle (persisted, independent of the board) ── */
let view = localStorage.getItem("raisedView") || "cols";
function applyView() {
  if (!["cols", "list"].includes(view)) view = "cols";
  $("#feed").className = "feed " + view;
  $$('[data-rview]').forEach((b) => b.classList.toggle("is-on", b.dataset.rview === view));
}
$$('[data-rview]').forEach((b) => b.addEventListener("click", () => {
  view = b.dataset.rview; localStorage.setItem("raisedView", view); applyView();
}));

applyView();
load();
setInterval(load, 60000);   // live: silent refresh every 60s
