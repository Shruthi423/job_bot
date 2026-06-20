/* ════════════════════════════════════════════════════════════════
   OpenTabs — front-end logic (job board)
   Reads ./jobs.json (written by opentabs.py) and renders three columns:
     New (≤24h, unapplied) · Not Applied (older, unapplied) · Applied.
   Deleted jobs go to a restorable Trash drawer. Clicking a tile opens
   the posting and asks "Did you apply?". The ONLY link to the Python
   bot is the jobs.json file.
   ════════════════════════════════════════════════════════════════ */

const NEW_MS = 24 * 3600 * 1000;        // "New" = posted in the last 24h
let JOBS = [];                          // raw data from jobs.json
let FUND = [];                          // raw data from funding.json (count only)

const state = {
  q: "", source: "", loc: "", date: "", visa: "",
  sort: localStorage.getItem("sort") || "new",   // new | location | salary
  size: +(localStorage.getItem("size") || 24),
  theme: localStorage.getItem("theme") || "dark",
  view: localStorage.getItem("view") || "board",  // "board" (cols) or "list"
  trashOpen: false,
};
const THEMES = ["dark", "paper", "blush", "mint", "cream"];
if (window.gsap && window.Flip) gsap.registerPlugin(Flip);

const $  = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ── Applied marks + Trash + Undo (all per-browser) ─────────────── */
function loadMarks() { try { return JSON.parse(localStorage.getItem("marks") || "{}"); } catch { return {}; } }
function saveMarks(m) { localStorage.setItem("marks", JSON.stringify(m)); }
let MARKS = loadMarks();                          // { jobId: "done" }
function isApplied(j) { return MARKS[j.id] === "done" || j.status === "applied"; }

function loadTrash() { try { return new Set(JSON.parse(localStorage.getItem("trash") || "[]")); } catch { return new Set(); } }
function saveTrash() { localStorage.setItem("trash", JSON.stringify([...TRASH])); }
let TRASH = loadTrash();                           // Set<jobId>

const UNDO_STACK = [];                             // {type:"mark",id,prev} | {type:"trash"|"restore",ids}
function pushUndo(e) { UNDO_STACK.push(e); refreshUndo(); }
function refreshUndo() { const b = $("#undoBtn"); if (b) b.disabled = UNDO_STACK.length === 0; }
function undoLast() {
  const e = UNDO_STACK.pop();
  if (!e) return;
  if (e.type === "mark") {
    if (e.prev === undefined) delete MARKS[e.id]; else MARKS[e.id] = e.prev;
    saveMarks(MARKS);
  } else if (e.type === "trash") {
    e.ids.forEach((id) => TRASH.delete(id)); saveTrash();
  } else if (e.type === "restore") {
    e.ids.forEach((id) => TRASH.add(id)); saveTrash();
  }
  refreshUndo();
  render(true);
}

/* ── helpers ──────────────────────────────────────────────────── */
function ago(when) {
  const d = (Date.now() - new Date(when).getTime()) / 1000;
  if (isNaN(d)) return "";
  if (d < 3600)  return Math.max(1, Math.floor(d / 60)) + "m ago";
  if (d < 86400) return Math.floor(d / 3600) + "h ago";
  return Math.floor(d / 86400) + "d ago";
}
// best available timestamp in ms — real posted_at if present, else first_seen
function jobTime(j) {
  if (j.posted_at && j.posted_at !== "Recently") {
    const t = Date.parse(j.posted_at);
    if (!isNaN(t)) return t;
  }
  return new Date(j.first_seen).getTime() || 0;
}
function postedAgo(j) { const t = jobTime(j); return t ? ago(t) : "recently"; }
function salaryNum(s) {
  const m = (s || "").replace(/,/g, "").match(/\$(\d+)(k)?/i);
  if (!m) return -1;
  return parseInt(m[1], 10) * (m[2] ? 1000 : 1);
}
// which location group a job falls in (for the Location filter)
function locGroup(j) {
  const t = (j.location || "").toLowerCase(), p = j.priority || 9;
  if (p === 1 || p === 2) return "sfbay";
  if (/new york|nyc|manhattan|brooklyn/.test(t)) return "ny";
  if (p === 5 || /remote/.test(t)) return "remote";
  return "us";
}
function bucket(j) {                      // which column a job belongs to
  if (isApplied(j)) return "app";
  const age = Date.now() - new Date(j.first_seen).getTime();
  return age <= NEW_MS ? "new" : "notapplied";
}

/* ── filtering + sorting ──────────────────────────────────────── */
function visible() {
  let out = JOBS.filter((j) => {
    if (TRASH.has(j.id)) return false;
    if (state.q) {
      const hay = (j.title + " " + j.company).toLowerCase();
      if (!hay.includes(state.q.toLowerCase())) return false;
    }
    if (state.source && j.source !== state.source) return false;
    if (state.loc && locGroup(j) !== state.loc) return false;
    if (state.date && Date.now() - jobTime(j) > (+state.date) * 3600 * 1000) return false;
    if (state.visa && (j.visa || "unknown") !== state.visa) return false;
    return true;
  });
  out.sort((a, b) => {
    if (state.sort === "new")    return jobTime(b) - jobTime(a);     // newest on top
    if (state.sort === "salary") return salaryNum(b.salary) - salaryNum(a.salary);
    const pa = a.priority || 9, pb = b.priority || 9;               // location
    if (pa !== pb) return pa - pb;
    return (b.first_seen || "").localeCompare(a.first_seen || "");
  });
  return out;
}

/* LinkedIn glyph — shown in place of the "Linkedin" source label */
const LI_SVG = '<svg class="ico-li" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" aria-label="LinkedIn"><path d="M216,24H40A16,16,0,0,0,24,40V216a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V40A16,16,0,0,0,216,24ZM96,176a8,8,0,0,1-16,0V112a8,8,0,0,1,16,0ZM88,96a12,12,0,1,1,12-12A12,12,0,0,1,88,96Zm96,80a8,8,0,0,1-16,0V140a20,20,0,0,0-40,0v36a8,8,0,0,1-16,0V112a8,8,0,0,1,15.79-1.78A36,36,0,0,1,184,140Z"></path></svg>';
/* Money glyph — replaces the 💰 emoji on "just raised" sources */
const MONEY_SVG = '<svg class="ico-money" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" aria-label="Just raised"><path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216Zm40-68a28,28,0,0,1-28,28h-4v8a8,8,0,0,1-16,0v-8H104a8,8,0,0,1,0-16h36a12,12,0,0,0,0-24H116a28,28,0,0,1,0-56h4V72a8,8,0,0,1,16,0v8h16a8,8,0,0,1,0,16H116a12,12,0,0,0,0,24h24A28,28,0,0,1,168,148Z"></path></svg>';
/* Globe glyph — company website link in the outreach row */
const WEB_SVG = '<svg width="12" height="12" fill="currentColor" viewBox="0 0 256 256" aria-hidden="true"><path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24ZM101.63,168h52.74C149,186.34,140,202.87,128,215.89,116,202.87,107,186.34,101.63,168ZM98,152a145.72,145.72,0,0,1,0-48h60a145.72,145.72,0,0,1,0,48ZM40,128a87.61,87.61,0,0,1,3.33-24H81.79a161.79,161.79,0,0,0,0,48H43.33A87.61,87.61,0,0,1,40,128ZM154.37,88H101.63C107,69.66,116,53.13,128,40.11,140,53.13,149,69.66,154.37,88Zm19.84,16h38.46a88.15,88.15,0,0,1,0,48H174.21a161.79,161.79,0,0,0,0-48Zm32.16-16H170.94a142.39,142.39,0,0,0-20.26-45A88.37,88.37,0,0,1,206.37,88ZM105.32,43A142.39,142.39,0,0,0,85.06,88H49.63A88.37,88.37,0,0,1,105.32,43ZM49.63,168H85.06a142.39,142.39,0,0,0,20.26,45A88.37,88.37,0,0,1,49.63,168Zm101.05,45a142.39,142.39,0,0,0,20.26-45h35.43A88.37,88.37,0,0,1,150.68,213Z"></path></svg>';
/* Small LinkedIn glyph for the outreach chips */
const LI_MINI = '<svg width="12" height="12" fill="currentColor" viewBox="0 0 256 256" aria-hidden="true"><path d="M216,24H40A16,16,0,0,0,24,40V216a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V40A16,16,0,0,0,216,24ZM96,176a8,8,0,0,1-16,0V112a8,8,0,0,1,16,0Zm-8-80a12,12,0,1,1,12-12A12,12,0,0,1,88,96Zm96,80a8,8,0,0,1-16,0V140a20,20,0,0,0-40,0v36a8,8,0,0,1-16,0V112a8,8,0,0,1,15.79-1.78A36,36,0,0,1,184,140Z"></path></svg>';
/* Outreach deep-links — free layer (no scraping, no API keys) */
const outreachUrls = {
  site: (co) => "https://duckduckgo.com/?q=" + encodeURIComponent("\\" + (co || "") + " official site"),
  company: (co) => "https://www.linkedin.com/search/results/companies/?keywords=" + encodeURIComponent(co || ""),
  founder: (nm, co) => "https://www.google.com/search?q=" +
    encodeURIComponent('site:linkedin.com/in "' + (nm || "") + '" ' + (co || "")),
};
function outreachHTML(j) {
  const founders = (j.founders || []).map((nm) =>
    `<a class="founder" href="${esc(outreachUrls.founder(nm, j.company))}" target="_blank" rel="noopener" ` +
    `title="Find ${esc(nm)} on LinkedIn">${esc(nm)}${LI_MINI}</a>`).join("");
  return `<div class="outreach">
        <a class="ol" href="${esc(outreachUrls.site(j.company))}" target="_blank" rel="noopener">${WEB_SVG}Website</a>
        <a class="ol" href="${esc(outreachUrls.company(j.company))}" target="_blank" rel="noopener">${LI_MINI}Company</a>
        ${founders ? `<span class="ol-lbl">Founders</span>${founders}` : ""}
      </div>`;
}
/* Trash glyph — delete button on each tile */
const TRASH_SVG = '<svg width="16" height="16" fill="currentColor" viewBox="0 0 256 256" aria-hidden="true"><path d="M216,48H176V40a24,24,0,0,0-24-24H104A24,24,0,0,0,80,40v8H40a8,8,0,0,0,0,16h8V208a16,16,0,0,0,16,16H192a16,16,0,0,0,16-16V64h8a8,8,0,0,0,0-16ZM96,40a8,8,0,0,1,8-8h48a8,8,0,0,1,8,8v8H96Zm96,168H64V64H192ZM112,104v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Zm48,0v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Z"></path></svg>';

function sourceLabel(src) {
  src = src || "";
  if (/just raised/i.test(src)) return MONEY_SVG + '<span>' + esc(src.replace(/^\s*💰\s*/, "")) + '</span>';
  if (/linkedin/i.test(src)) return LI_SVG + '<span>LinkedIn</span>';
  return esc(src);
}

/* roll a number element from its current value to a new one */
function rollTo(el, val) {
  if (!el) return;
  const from = parseInt(el.textContent, 10) || 0;
  if (from === val || !window.gsap) { el.textContent = val; return; }
  const o = { v: from };
  gsap.to(o, { v: val, duration: 0.5, ease: "power2.out",
    onUpdate: () => (el.textContent = Math.round(o.v)) });
}
/* move/remove a card with a GSAP Flip transition */
function flipMove(mutate) {
  if (window.gsap && window.Flip) {
    const s = Flip.getState("main .job");
    mutate(); render(false);
    Flip.from(s, { duration: 0.5, ease: "power3.inOut", absolute: true,
      onEnter: (els) => gsap.fromTo(els, { opacity: 0 }, { opacity: 1, duration: 0.3 }) });
  } else { mutate(); render(false); }
}
function reveal() {
  if (!window.gsap) return;
  gsap.from("main .job", { y: 14, opacity: 0, duration: 0.5, ease: "power3.out", stagger: 0.02, overwrite: true });
}

/* ── rendering ────────────────────────────────────────────────── */
function jobHTML(j, n) {
  const idx = String(n).padStart(2, "0");
  const badges =
    (j.is_new_grad ? '<span class="badge">New Grad</span>' : "") +
    (j.is_big_tech ? '<span class="badge">Big Tech</span>' : "") +
    (j.visa === "yes" ? '<span class="badge visa-yes">Visa ✓</span>'
     : j.visa === "no" ? '<span class="badge visa-no">No visa</span>' : "");
  return `<div class="job" data-id="${esc(j.id)}" data-url="${esc(j.url || "#")}" data-title="${esc(j.title)}" data-flip-id="${esc(j.id)}">
      <div class="job-top">
        <span class="idx">${idx}</span>
        <span class="co">${esc(j.company)}</span>
        <span class="src">${sourceLabel(j.source)}</span>
      </div>
      <div class="job-title">${esc(j.title)}</div>
      <div class="job-meta">
        ${esc(j.location || "—")}<span class="sep">/</span>${esc(j.salary || "—")}<span class="sep">/</span>Posted ${postedAgo(j)}
      </div>
      ${outreachHTML(j)}
      <div class="job-foot">
        <span class="badges">${badges}</span>
        <span class="actions"><button class="act icon del" data-act="delete" title="Delete" aria-label="Delete">${TRASH_SVG}</button></span>
      </div>
    </div>`;
}
function trashHTML(j, n) {
  const idx = String(n).padStart(2, "0");
  return `<div class="job" data-id="${esc(j.id)}" data-url="${esc(j.url || "#")}" data-title="${esc(j.title)}">
      <div class="job-top">
        <span class="idx">${idx}</span>
        <span class="co">${esc(j.company)}</span>
        <span class="src">${sourceLabel(j.source)}</span>
      </div>
      <div class="job-title">${esc(j.title)}</div>
      <div class="job-meta">${esc(j.location || "—")}<span class="sep">/</span>${esc(j.salary || "—")}</div>
      <div class="job-foot">
        <span class="badges"></span>
        <span class="actions"><button class="act ghost" data-act="restore">Restore</button></span>
      </div>
    </div>`;
}

function render(animate) {
  const jobs = visible();
  const groups = { new: [], notapplied: [], app: [] };
  jobs.forEach((j) => groups[bucket(j)].push(j));
  groups.app.sort((a, b) => jobTime(b) - jobTime(a));   // most recently applied first

  ["new", "notapplied", "app"].forEach((k) => {
    $("#rows-" + k).innerHTML =
      groups[k].length ? groups[k].map((j, i) => jobHTML(j, i + 1)).join("")
                       : '<div class="col-empty">Nothing here.</div>';
    $$(`[data-count="${k}"]`).forEach((el) => (el.textContent = groups[k].length));
  });

  // Trash drawer (not filtered by the board filters — it's a holding area)
  const trashed = JOBS.filter((j) => TRASH.has(j.id));
  $("#rows-trash").innerHTML =
    trashed.length ? trashed.map((j, i) => trashHTML(j, i + 1)).join("")
                   : '<div class="col-empty">Trash is empty.</div>';
  $$('[data-count="trash"]').forEach((el) => (el.textContent = trashed.length));

  $("#count").textContent = jobs.length;
  $("#status").textContent = JOBS.length ? "Updated " + new Date().toLocaleTimeString() : "No data yet";

  let open = 0, done = 0;
  JOBS.forEach((j) => { if (TRASH.has(j.id)) return; bucket(j) === "app" ? done++ : open++; });
  rollTo($("#statOpen"), open);
  rollTo($("#statDone"), done);

  refreshUndo();
  if (animate) reveal();
}

/* Funding count on the "Just Raised" nav tab */
function renderFunding() {
  const live = FUND.filter((f) => f.status !== "dismissed");
  $$('[data-count="raised"]').forEach((el) => (el.textContent = live.length));
}

/* ── apply persisted view/size/theme/sort/drawer to the DOM ────── */
function applyChrome() {
  if (!THEMES.includes(state.theme)) state.theme = "dark";
  document.documentElement.setAttribute("data-theme", state.theme);
  $$('.sw').forEach((b) => b.classList.toggle("is-on", b.dataset.theme === state.theme));
  $("main").className = state.view;
  $$('[data-view]').forEach((b) => b.classList.toggle("is-on", b.dataset.view === state.view));
  $$('[data-sort]').forEach((b) => b.classList.toggle("is-on", b.dataset.sort === state.sort));
  document.documentElement.style.setProperty("--spec-size", state.size + "px");
  $("#size").value = state.size;
  $("#sizeVal").textContent = state.size;
  document.body.classList.toggle("trash-open", state.trashOpen);
  refreshUndo();
}

/* ── "Did you apply?" prompt — flips in on the clicked tile itself ── */
function clearAsk() {
  document.querySelectorAll(".job-ask").forEach((e) => e.remove());
  document.querySelectorAll(".job.asking").forEach((c) => c.classList.remove("asking"));
}
function askOnCard(card) {
  clearAsk();
  card.classList.add("asking");
  const ov = document.createElement("div");
  ov.className = "job-ask";
  ov.innerHTML = '<span class="ask-q">Did you apply to this role?</span>' +
    '<span class="ask-btns"><button class="ask-no" data-ask="no">No</button>' +
    '<button class="ask-yes" data-ask="yes">Yes, applied</button></span>';
  card.appendChild(ov);
  if (window.gsap) gsap.from(ov, { rotationX: -90, opacity: 0, duration: 0.35, ease: "power3.out", transformOrigin: "top center" });
}

/* ── Clear-all confirm popup ───────────────────────────────────── */
const SECTION_LABELS = { new: "New", notapplied: "Not Applied", app: "Applied" };
let pendingClear = null;
function closeModal() { $("#modalScrim").hidden = true; pendingClear = null; }
function openModal(k) {
  pendingClear = k;
  $("#modalMsg").innerHTML = `This will move all listings in <b>“${esc(SECTION_LABELS[k] || k)}”</b> to Trash. Continue?`;
  $("#modalScrim").hidden = false;
}

/* ── wire up all the controls ─────────────────────────────────── */
function bind() {
  $("#q").addEventListener("input", (e) => { state.q = e.target.value; render(false); });
  $("#fSource").addEventListener("change", (e) => { state.source = e.target.value; render(true); });
  $("#fLoc").addEventListener("change",   (e) => { state.loc = e.target.value; render(true); });
  $("#fDate").addEventListener("change",  (e) => { state.date = e.target.value; render(true); });
  $("#fVisa").addEventListener("change",  (e) => { state.visa = e.target.value; render(true); });

  $$('[data-sort]').forEach((b) => b.addEventListener("click", () => {
    state.sort = b.dataset.sort; localStorage.setItem("sort", state.sort);
    $$('[data-sort]').forEach((x) => x.classList.toggle("is-on", x === b));
    render(true);
  }));

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

  // nav tabs smooth-scroll to their column
  $$('[data-jump]').forEach((t) => t.addEventListener("click", (e) => {
    e.preventDefault();
    const el = $("#sec-" + t.dataset.jump); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }));

  $("#menuBtn").addEventListener("click", () => $("#controls").classList.toggle("open"));

  // ── Trash drawer (collapses from the right) ──
  const setTrash = (open) => { state.trashOpen = open; document.body.classList.toggle("trash-open", open); };
  $("#tabTrash").addEventListener("click", () => setTrash(!state.trashOpen));
  const trashNav = $("#trashNav"); if (trashNav) trashNav.addEventListener("click", () => setTrash(true));
  $$('.drawer-close').forEach((b) => b.addEventListener("click", () => setTrash(false)));
  $("#drawerScrim").addEventListener("click", () => setTrash(false));

  // global Undo
  $("#undoBtn").addEventListener("click", undoLast);

  // ── Clear all → move a column to Trash (confirm) ──
  $$('.clear-all').forEach((b) => b.addEventListener("click", () => openModal(b.dataset.clear)));
  $("#modalNo").addEventListener("click", closeModal);
  $("#modalScrim").addEventListener("click", (e) => { if (e.target === $("#modalScrim")) closeModal(); });
  $("#modalYes").addEventListener("click", () => {
    if (!pendingClear) return;
    const ids = visible().filter((j) => bucket(j) === pendingClear).map((j) => j.id);
    if (ids.length) { pushUndo({ type: "trash", ids }); ids.forEach((id) => TRASH.add(id)); saveTrash(); }
    closeModal(); render(true);
  });

  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { setTrash(false); clearAsk(); closeModal(); } });

  // ── Tile interactions: apply-prompt / delete / restore, or open posting ──
  const onCardClick = (e) => {
    const card = e.target.closest(".job"); if (!card) return;
    // outreach links (website / LinkedIn / founder) open on their own — don't
    // also open the posting or fire the "did you apply?" prompt
    if (e.target.closest(".outreach")) return;
    const id = card.dataset.id, url = card.dataset.url;
    const ask = e.target.closest('[data-ask]');
    if (ask) {                                // answered the on-tile prompt
      pushUndo({ type: "mark", id, prev: MARKS[id] });
      if (ask.dataset.ask === "yes") flipMove(() => { MARKS[id] = "done"; saveMarks(MARKS); });
      else flipMove(() => { delete MARKS[id]; saveMarks(MARKS); });
      return;
    }
    if (e.target.closest('[data-act="restore"]')) {
      pushUndo({ type: "restore", ids: [id] }); TRASH.delete(id); saveTrash(); render(true); return;
    }
    if (e.target.closest('[data-act="delete"]')) {
      pushUndo({ type: "trash", ids: [id] });
      const drop = () => { TRASH.add(id); saveTrash(); render(false); };
      if (window.gsap) gsap.to(card, { opacity: 0, duration: 0.25, ease: "power1.out", onComplete: drop }); else drop();
      return;
    }
    // click anywhere else on the tile → open the posting, then ask on the tile
    if (url && url !== "#") window.open(url, "_blank", "noopener");
    if (!card.closest("#drawerTrash")) askOnCard(card);
  };
  $("main").addEventListener("click", onCardClick);
  $("#drawerTrash").addEventListener("click", onCardClick);
}

/* ── load data + refresh loop ─────────────────────────────────── */
function populateSources() {
  const sources = [...new Set(JOBS.map((j) => j.source).filter(Boolean))].sort();
  const sel = $("#fSource");
  sel.innerHTML = '<option value="">All sources</option>' +
    sources.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  sel.value = state.source;
}

function load(animate) {
  fetch("./jobs.json?_=" + Date.now())
    .then((r) => (r.ok ? r.json() : []))
    .then((data) => { JOBS = Array.isArray(data) ? data : []; populateSources(); render(animate); })
    .catch(() => { $("#status").textContent = "No data yet"; });
  fetch("./funding.json?_=" + Date.now())
    .then((r) => (r.ok ? r.json() : []))
    .then((data) => { FUND = Array.isArray(data) ? data : []; renderFunding(); })
    .catch(() => {});
}

// arriving from the Just Raised page's Trash tab? open the trash drawer
if (location.hash === "#trash") state.trashOpen = true;

applyChrome();
bind();
load(true);
setInterval(() => load(false), 60000);
