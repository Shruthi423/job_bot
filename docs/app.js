/* ════════════════════════════════════════════════════════════════
   OpenTabs — front-end logic
   Reads ./jobs.json (written by opentabs.py), renders the three
   sections, and handles search / filters / sort / views / theme.
   The ONLY link to the Python bot is this jobs.json file.
   ════════════════════════════════════════════════════════════════ */

const NEW_MS = 24 * 3600 * 1000;        // "New" = found in the last 24h
let JOBS = [];                          // raw data from jobs.json
let FUND = [];                          // raw data from funding.json (raises)

// current UI state (some values restored from localStorage)
const state = {
  q: "",
  source: "",
  loc: "",
  badge: "",
  sort: "priority",
  size: +(localStorage.getItem("size") || 24),
  theme: localStorage.getItem("theme") || "dark",
  view: localStorage.getItem("view") || "board",   // "board" (3 cols) or "list"
};
const THEMES = ["dark", "paper", "blush", "mint", "cream"];
if (window.gsap && window.Flip) gsap.registerPlugin(Flip);

/* ── Your Applied / Dismissed marks, saved in this browser ──────── */
function loadMarks() { try { return JSON.parse(localStorage.getItem("marks") || "{}"); } catch { return {}; } }
function saveMarks(m) { localStorage.setItem("marks", JSON.stringify(m)); }
let MARKS = loadMarks();                          // { jobId: "done" | "yet" }
function effStatus(j) {
  const m = MARKS[j.id];
  if (m === "done" || j.status === "applied") return "done";
  if (m === "yet") return "yet";
  return "active";                                // untriaged / fresh
}
function applyMark(id, act) {
  if (act === "reset") delete MARKS[id];
  else MARKS[id] = act;                            // "done" | "yet"
  saveMarks(MARKS);
}
// move a card between sections with a GSAP Flip transition (card "flies")
function flipMove(id, act) {
  if (window.gsap && window.Flip) {
    const state = Flip.getState("main .job");
    applyMark(id, act);
    render(false);
    Flip.from(state, {
      duration: 0.55, ease: "power3.inOut", absolute: true,
      onEnter: (els) => gsap.fromTo(els, { opacity: 0 }, { opacity: 1, duration: 0.3 }),
    });
  } else {
    applyMark(id, act);
    render(false);
  }
}
// draw the strikethrough across the title, then run the callback
function drawStrike(title, done) {
  if (!title || !window.gsap) { done(); return; }
  title.classList.add("striking");
  gsap.fromTo(title, { "--strike": "0%" }, {
    "--strike": "100%", duration: 0.34, ease: "power2.out",
    onComplete: () => { title.classList.remove("striking"); done(); },
  });
}
// roll a number element from its current value to a new one
function rollTo(el, val) {
  const from = parseInt(el.textContent, 10) || 0;
  if (from === val || !window.gsap) { el.textContent = val; return; }
  const o = { v: from };
  gsap.to(o, { v: val, duration: 0.5, ease: "power2.out",
    onUpdate: () => (el.textContent = Math.round(o.v)) });
}

const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ── helpers ──────────────────────────────────────────────────── */
function ago(when) {
  const d = (Date.now() - new Date(when).getTime()) / 1000;
  if (d < 3600)  return Math.max(1, Math.floor(d / 60)) + "m ago";
  if (d < 86400) return Math.floor(d / 3600) + "h ago";
  return Math.floor(d / 86400) + "d ago";
}
// how long ago the job was posted: use posted_at if it's a real date,
// else fall back to first_seen (bot catches jobs within ~2 min of posting)
function postedAgo(j) {
  if (j.posted_at && j.posted_at !== "Recently") {
    const t = Date.parse(j.posted_at);
    if (!isNaN(t)) return ago(t);
  }
  return ago(j.first_seen);
}
function salaryNum(s) {                  // first $ figure, for sorting
  const m = (s || "").replace(/,/g, "").match(/\$(\d+)(k)?/i);
  if (!m) return -1;
  return parseInt(m[1], 10) * (m[2] ? 1000 : 1);
}
function bucket(j) {                      // which section a job belongs to
  const s = effStatus(j);
  if (s === "done") return "app";        // Applied
  if (s === "yet") return "yet";         // Not yet → Yet to Apply
  if (Date.now() - new Date(j.first_seen).getTime() <= NEW_MS) return "new";
  return "yet";                          // older & untouched → Yet to Apply
}

/* ── filtering + sorting ──────────────────────────────────────── */
function visible() {
  let out = JOBS.filter((j) => {
    if (state.q) {
      const hay = (j.title + " " + j.company).toLowerCase();
      if (!hay.includes(state.q.toLowerCase())) return false;
    }
    if (state.source && j.source !== state.source) return false;
    if (state.loc && !(j.location || "").toLowerCase().includes(state.loc)) return false;
    if (state.badge === "ng" && !j.is_new_grad) return false;
    if (state.badge === "bt" && !j.is_big_tech) return false;
    return true;
  });
  out.sort((a, b) => {
    if (state.sort === "priority") {                 // SF → Bay → Seattle/LA/NY/Philly → US → remote
      const pa = a.priority || 9, pb = b.priority || 9;
      if (pa !== pb) return pa - pb;
      return (b.first_seen || "").localeCompare(a.first_seen || "");
    }
    if (state.sort === "salary")  return salaryNum(b.salary) - salaryNum(a.salary);
    if (state.sort === "company") return (a.company || "").localeCompare(b.company || "");
    return (b.first_seen || "").localeCompare(a.first_seen || ""); // newest
  });
  return out;
}

/* LinkedIn glyph — shown in place of the "Linkedin" source label */
const LI_SVG = '<svg class="ico-li" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" aria-label="LinkedIn"><path d="M216,24H40A16,16,0,0,0,24,40V216a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V40A16,16,0,0,0,216,24Zm0,192H40V40H216V216ZM96,112v64a8,8,0,0,1-16,0V112a8,8,0,0,1,16,0Zm88,28v36a8,8,0,0,1-16,0V140a20,20,0,0,0-40,0v36a8,8,0,0,1-16,0V112a8,8,0,0,1,15.79-1.78A36,36,0,0,1,184,140ZM100,84A12,12,0,1,1,88,72,12,12,0,0,1,100,84Z"></path></svg>';
/* Money glyph — replaces the 💰 emoji on "just raised" sources */
const MONEY_SVG = '<svg class="ico-money" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" aria-label="Just raised"><path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216Zm40-68a28,28,0,0,1-28,28h-4v8a8,8,0,0,1-16,0v-8H104a8,8,0,0,1,0-16h36a12,12,0,0,0,0-24H116a28,28,0,0,1,0-56h4V72a8,8,0,0,1,16,0v8h16a8,8,0,0,1,0,16H116a12,12,0,0,0,0,24h24A28,28,0,0,1,168,148Z"></path></svg>';
function sourceLabel(src) {
  src = src || "";
  if (/just raised/i.test(src)) {                  // "💰 Anthropic (just raised)"
    return MONEY_SVG + '<span>' + esc(src.replace(/^\s*💰\s*/, "")) + '</span>';
  }
  if (/linkedin/i.test(src)) return LI_SVG + '<span>LinkedIn</span>';
  return esc(src);
}

/* ── rendering ────────────────────────────────────────────────── */
function jobHTML(j, n, k) {
  const badges =
    (j.is_new_grad ? '<span class="badge">New Grad</span>' : "") +
    (j.is_big_tech ? '<span class="badge">Big Tech</span>' : "");
  const href = j.url ? esc(j.url) : "#";
  const idx = String(n).padStart(2, "0");
  let actions;
  if (k === "app") {                       // Applied → Undo
    actions = '<button class="act ghost" data-act="reset">Undo</button>';
  } else if (k === "new") {                // New → Done / Not yet
    actions = '<button class="act done" data-act="done">Done</button>' +
              '<button class="act ghost" data-act="yet">Not yet</button>';
  } else {                                 // Yet to Apply → Done (+ Undo if moved here)
    actions = '<button class="act done" data-act="done">Done</button>' +
              (MARKS[j.id] === "yet" ? '<button class="act ghost" data-act="reset">Undo</button>' : "");
  }
  return `<div class="job" data-id="${esc(j.id)}" data-flip-id="${esc(j.id)}">
      <div class="job-top">
        <span class="idx">${idx}</span>
        <span class="co">${esc(j.company)}</span>
        <span class="src">${sourceLabel(j.source)}</span>
      </div>
      <a class="job-title" href="${href}" target="_blank" rel="noopener">${esc(j.title)}</a>
      <div class="job-meta">
        ${esc(j.location || "—")}<span class="sep">/</span>${esc(j.salary || "—")}<span class="sep">/</span>Posted ${postedAgo(j)}
      </div>
      <div class="job-foot">
        <span class="badges">${badges}</span>
        <span class="actions">${actions}</span>
      </div>
    </div>`;
}

function render(animate) {
  const jobs = visible();
  const groups = { new: [], yet: [], app: [] };
  jobs.forEach((j) => groups[bucket(j)].push(j));

  ["new", "yet", "app"].forEach((k) => {
    $("#rows-" + k).innerHTML =
      groups[k].length ? groups[k].map((j, i) => jobHTML(j, i + 1, k)).join("")
                       : '<div class="col-empty">Nothing here.</div>';
    $$(`[data-count="${k}"]`).forEach((el) => (el.textContent = groups[k].length));
  });

  $("#count").textContent = jobs.length;
  $("#status").textContent = JOBS.length
    ? "Updated " + new Date().toLocaleTimeString()
    : "No data yet";

  // live footer stats across ALL jobs (ignores filters): open vs done
  let open = 0, done = 0;
  JOBS.forEach((j) => (bucket(j) === "app" ? done++ : open++));
  rollTo($("#statOpen"), open);
  rollTo($("#statDone"), done);

  if (animate) reveal();
}

/* ── Funding lives on its own page (raised.html). Here we only surface
   the count on the "Just Raised" nav tab. ───────────────────────── */
function renderFunding() {
  const live = FUND.filter((f) => f.status !== "dismissed");
  $$('[data-count="raised"]').forEach((el) => (el.textContent = live.length));
}

/* buttery staggered entrance for the cards (GSAP) */
function reveal() {
  if (!window.gsap) return;
  gsap.from("main .job", {
    y: 14, opacity: 0, duration: 0.5, ease: "power3.out", stagger: 0.02,
    overwrite: true,
  });
}

/* ── apply persisted view/size/theme to the DOM ───────────────── */
function applyChrome() {
  if (!THEMES.includes(state.theme)) state.theme = "dark";
  document.documentElement.setAttribute("data-theme", state.theme);
  $$('.sw').forEach((b) => b.classList.toggle("is-on", b.dataset.theme === state.theme));
  $("main").className = state.view;
  $$('[data-view]').forEach((b) => b.classList.toggle("is-on", b.dataset.view === state.view));
  document.documentElement.style.setProperty("--spec-size", state.size + "px");
  $("#size").value = state.size;
  $("#sizeVal").textContent = state.size;
}

/* ── wire up all the controls ─────────────────────────────────── */
function bind() {
  // search updates instantly (no animation, so typing stays smooth)
  $("#q").addEventListener("input", (e) => { state.q = e.target.value; render(false); });

  $("#fSource").addEventListener("change", (e) => { state.source = e.target.value; render(true); });
  $("#fLoc").addEventListener("change",   (e) => { state.loc = e.target.value; render(true); });
  $("#fBadge").addEventListener("change", (e) => { state.badge = e.target.value; render(true); });

  $$('[data-sort]').forEach((b) => b.addEventListener("click", () => {
    state.sort = b.dataset.sort;
    $$('[data-sort]').forEach((x) => x.classList.toggle("is-on", x === b));
    render(true);
  }));

  // Column / List view toggle
  $$('[data-view]').forEach((b) => b.addEventListener("click", () => {
    state.view = b.dataset.view; localStorage.setItem("view", state.view);
    applyChrome(); reveal();
  }));

  $("#size").addEventListener("input", (e) => {
    state.size = +e.target.value; localStorage.setItem("size", state.size);
    document.documentElement.style.setProperty("--spec-size", state.size + "px");
    $("#sizeVal").textContent = state.size;
  });

  $$('.sw').forEach((b) => b.addEventListener("click", () => {
    state.theme = b.dataset.theme; localStorage.setItem("theme", state.theme); applyChrome();
  }));

  $("#resetBtn").addEventListener("click", () => {
    Object.assign(state, { q: "", source: "", loc: "", badge: "", sort: "priority" });
    $("#q").value = ""; $("#fSource").value = ""; $("#fLoc").value = ""; $("#fBadge").value = "";
    $$('[data-sort]').forEach((x) => x.classList.toggle("is-on", x.dataset.sort === "priority"));
    render(true);
  });

  // nav tabs smooth-scroll to their section
  $$('[data-jump]').forEach((t) => t.addEventListener("click", (e) => {
    e.preventDefault();
    $("#sec-" + t.dataset.jump).scrollIntoView({ behavior: "smooth", block: "start" });
  }));

  // mobile: hamburger reveals the filter bars
  $("#menuBtn").addEventListener("click", () => $("#controls").classList.toggle("open"));

  // Done / Not yet / Undo buttons on each card (event delegation)
  $("main").addEventListener("click", (e) => {
    const btn = e.target.closest(".act");
    if (!btn) return;
    const card = e.target.closest(".job");
    if (!card || !card.dataset.id) return;
    const id = card.dataset.id, act = btn.dataset.act;
    if (act === "done") {
      // strike the title, then fly the card into Applied
      drawStrike(card.querySelector(".job-title"), () => flipMove(id, act));
    } else {
      flipMove(id, act);
    }
  });
}

/* ── load data + refresh loop ─────────────────────────────────── */
function populateSources() {
  const sources = [...new Set(JOBS.map((j) => j.source).filter(Boolean))].sort();
  const sel = $("#fSource");
  sel.innerHTML = '<option value="">All</option>' +
    sources.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  sel.value = state.source;
}

function load(animate) {
  fetch("./jobs.json?_=" + Date.now())
    .then((r) => (r.ok ? r.json() : []))
    .then((data) => { JOBS = Array.isArray(data) ? data : []; populateSources(); render(animate); })
    .catch(() => { $("#status").textContent = "No data yet"; });
  // funding.json is optional — silently ignore if the radar isn't enabled
  fetch("./funding.json?_=" + Date.now())
    .then((r) => (r.ok ? r.json() : []))
    .then((data) => { FUND = Array.isArray(data) ? data : []; renderFunding(); })
    .catch(() => {});
}

applyChrome();
bind();
load(true);                          // animate on first paint
setInterval(() => load(false), 60000);    // live: silent refresh every 60s
