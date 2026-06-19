"""
╔══════════════════════════════════════════════════════════════════╗
║   🎨  UX/DESIGN JOB ALERT BOT  — Final Version                  ║
║   Channel: 🎨 Job Alerts                                         ║
║   Engine: JobSpy (LinkedIn, Indeed, Glassdoor, ZipRecruiter)     ║
║   + RSS boards (Remotive, Dribbble, WeWorkRemotely etc.)         ║
║   Alerts: 2 min first · 7 min reminder                          ║
║   Graduating: May 2026 🎓                                        ║
╚══════════════════════════════════════════════════════════════════╝
"""

import json, os, time, hashlib, logging, schedule, requests, re, html, subprocess, math
import feedparser
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()  # read secrets from a local .env file (never committed)

# ─────────────────────────────────────────────────────────────────
#  ⚙️  CONFIGURATION — secrets loaded from .env, rest pre-filled
# ─────────────────────────────────────────────────────────────────
CONFIG = {
    "TELEGRAM_BOT_TOKEN": os.environ["TELEGRAM_BOT_TOKEN"],
    "TELEGRAM_CHAT_ID":   os.environ["TELEGRAM_CHAT_ID"],
    # ── Funding alerts → separate channel. CHAT_ID enables the feature;
    #    TOKEN falls back to the job bot's token when left blank. ──
    "TELEGRAM_FUNDING_BOT_TOKEN": os.environ.get("TELEGRAM_FUNDING_BOT_TOKEN", "").strip()
                                  or os.environ["TELEGRAM_BOT_TOKEN"],
    "TELEGRAM_FUNDING_CHAT_ID":   os.environ.get("TELEGRAM_FUNDING_CHAT_ID", "").strip(),
    "POLL_INTERVAL_MINUTES": 15,
    "REMINDER_MINUTES":      30,
    "HEARTBEAT_HOURS":       1,
    "DAILY_DIGEST_HOUR":     9,
    "HOURS_OLD":             3,
    "RESULTS_PER_SEARCH":    25,
    "SEEN_FILE":    "seen_jobs.json",
    "PENDING_FILE": "pending_jobs.json",
    "STORE_FILE":   "jobs_store.json",      # authoritative job records + status (local)
    "WEB_FILE":     "docs/jobs.json",        # derived data the website reads (published)
    # ── Funding pipeline state (local) + published data file ──
    "SEEN_FUNDING_FILE":    "seen_funding.json",
    "PENDING_FUNDING_FILE": "pending_funding.json",
    "FUNDING_STORE_FILE":   "funding_store.json",
    "FUNDING_WEB_FILE":     "docs/funding.json",
    "SITE_DIR":     "docs",                  # GitHub Pages serves from /docs on main
    "TG_OFFSET_FILE": "tg_offset.json",      # last processed Telegram update id
    "LOG_FILE":     "job_bot.log",
    "TIMEZONE":     "America/Los_Angeles",
    "NEW_HOURS":      24,                     # jobs newer than this show under "New"
    "PUBLISH_TO_GIT": True,                   # auto commit+push the dashboard each cycle
    "GITHUB_USER":  "Shruthi423",             # GitHub username (for the dashboard URL)
    "GITHUB_REPO":  "OpenTabs",               # repo name
}

TZ = ZoneInfo(CONFIG["TIMEZONE"])
def now_pt(): return datetime.now(TZ)

# ─────────────────────────────────────────────────────────────────
#  🎯  SEARCH QUERIES
# ─────────────────────────────────────────────────────────────────
SEARCH_QUERIES = [
    "product designer",
    "UX designer",
    "UI designer",
    "junior product designer",
    "junior UX designer",
    "associate product designer",
    "entry level UX designer",
    "new grad designer",
    "founding designer",
    "founding product designer",
    "UX researcher",
    "user researcher",
    "design systems designer",
    "interaction designer",
    "visual designer",
]

# US-focused. "United States" pulls nationwide (LinkedIn/Indeed); the
# location_rank() filter then keeps US-only and ranks by priority.
LOCATIONS = [
    "San Francisco, CA",
    "San Francisco Bay Area, CA",
    "United States",
]

# ─────────────────────────────────────────────────────────────────
#  🏢  BIG TECH LIST
# ─────────────────────────────────────────────────────────────────
BIG_TECH = {
    "google", "meta", "apple", "amazon", "netflix", "microsoft",
    "uber", "airbnb", "stripe", "openai", "anthropic", "figma",
    "notion", "slack", "dropbox", "lyft", "pinterest", "salesforce",
    "adobe", "canva", "linear", "vercel", "databricks", "robinhood",
    "coinbase", "doordash", "instacart", "reddit", "asana", "airtable",
    "miro", "webflow", "brex", "rippling", "scale ai", "perplexity",
    "cursor", "replit", "twitch", "snap", "bytedance", "tiktok",
    "palantir", "spacex", "tesla", "waymo", "mistral", "cohere",
}

# ─────────────────────────────────────────────────────────────────
#  🔍  RELEVANCE FILTER
# ─────────────────────────────────────────────────────────────────
INCLUDE = [
    "ux", "ui", "user experience", "user interface", "product designer",
    "interaction designer", "visual designer", "ux researcher",
    "user researcher", "design researcher", "design systems",
    "design technologist", "service designer", "founding designer",
    "motion designer", "brand designer",
]
EXCLUDE = [
    "graphic designer", "fashion", "interior design", "industrial design",
    "game designer", "floral", "packaging", "print designer",
    "instructional designer", "curriculum", "learning designer",
    "software engineer", "data engineer", "devops", "web developer",
    # seniority — we want roles for ≤4 years of experience
    "senior", "staff", "principal", "lead", "director", "head of",
    "vp ", "vice president", "manager",
]
NEW_GRAD_SIGNALS = [
    "new grad", "new graduate", "entry level", "entry-level", "junior",
    "associate", "0-2 years", "0-1 year", "recent graduate",
    "early career", "2026", "2025 grad",
]

def _kw_hit(kw: str, text: str) -> bool:
    # Short ambiguous tokens (ui/ux) must match as whole words, else
    # "recrUIter", "bUIld", "deluXe"… create false design matches.
    if len(kw) <= 2:
        return re.search(rf"\b{re.escape(kw)}\b", text) is not None
    return kw in text

def _too_senior(text: str) -> bool:
    # Exclude roles whose MINIMUM required experience is 5+ years.
    # "3-5 years" → min 3 (kept); "5+ years" / "6 years" → min 5+ (dropped).
    for m in re.finditer(r'(\d+)\s*\+?\s*(?:-|to|–|—)?\s*\d*\s*(?:years|yrs)\b', text):
        if int(m.group(1)) >= 5:
            return True
    return False

def classify(title: str, company: str = "", description: str = "") -> dict:
    text = f"{title} {description}".lower()
    tl   = title.lower()
    co   = company.lower()
    for ex in EXCLUDE:
        if ex in tl:
            return {"relevant": False}
    if _too_senior(text):
        return {"relevant": False}
    if not any(_kw_hit(kw, text) for kw in INCLUDE):
        return {"relevant": False}
    return {
        "relevant":    True,
        "is_new_grad": any(s in text for s in NEW_GRAD_SIGNALS),
        "is_big_tech": any(bt in co for bt in BIG_TECH),
    }

# ─────────────────────────────────────────────────────────────────
#  📝  LOGGING
# ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(CONFIG["LOG_FILE"]), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
#  💾  STATE
# ─────────────────────────────────────────────────────────────────
def load_json(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except:
            pass
    return default

def save_json(path, data):
    json.dump(data, open(path, "w"), indent=2)

def load_seen() -> set:    return set(load_json(CONFIG["SEEN_FILE"], []))
def save_seen(s):          save_json(CONFIG["SEEN_FILE"], list(s))
def load_pending() -> list: return load_json(CONFIG["PENDING_FILE"], [])
def save_pending(p):       save_json(CONFIG["PENDING_FILE"], p)

# ── Website job store (jid → record with status + first_seen) ──
def load_store() -> dict:  return load_json(CONFIG["STORE_FILE"], {})
def save_store(s):         save_json(CONFIG["STORE_FILE"], s)
def load_offset() -> int:  return int(load_json(CONFIG["TG_OFFSET_FILE"], 0))
def save_offset(o):        save_json(CONFIG["TG_OFFSET_FILE"], o)

# ── Backoff tracker ──
BACKOFF = {}
def is_cooling(source): return now_pt() < datetime.fromisoformat(BACKOFF[source]) if source in BACKOFF else False
def set_cooldown(source, mins=30):
    BACKOFF[source] = (now_pt() + timedelta(minutes=mins)).isoformat()
    log.warning(f"⏸ {source} cooling down {mins} min")

def job_id(title, company, location):
    loc = location.lower()
    if any(x in loc for x in ["san francisco", "bay area", "palo alto", "mountain view", "sunnyvale", "san jose"]):
        loc = "bayarea"
    elif "remote" in loc:
        loc = "remote"
    key = f"{title.lower().strip()}|{company.lower().strip()}|{loc}"
    return hashlib.md5(key.encode()).hexdigest()

# ─────────────────────────────────────────────────────────────────
#  📬  TELEGRAM ONLY
# ─────────────────────────────────────────────────────────────────
def send_telegram(msg: str, reply_markup: dict = None,
                  token: str = None, chat_id: str = None) -> bool:
    # Defaults target the job channel; pass token/chat_id to reach another
    # channel (e.g. the funding channel).
    token   = token or CONFIG["TELEGRAM_BOT_TOKEN"]
    chat_id = chat_id or CONFIG["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id":    chat_id,
        "text":       msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            log.error(f"Telegram error {r.status_code}: {r.text[:100]}")
            return False
        return True
    except Exception as e:
        log.error(f"Telegram: {e}")
        return False

def send_funding(msg: str) -> bool:
    return send_telegram(msg, token=CONFIG["TELEGRAM_FUNDING_BOT_TOKEN"],
                         chat_id=CONFIG["TELEGRAM_FUNDING_CHAT_ID"])

def funding_enabled() -> bool:
    return bool(CONFIG["TELEGRAM_FUNDING_CHAT_ID"])

def notify(job: dict, reminder: bool = False, jid: str = ""):
    title   = job.get("title", "?")
    company = job.get("company", "?")
    loc     = job.get("location", "?")
    salary  = job.get("salary", "Not listed")
    url     = job.get("url", "")
    source  = job.get("source", "")
    ng      = job.get("is_new_grad", False)
    bt      = job.get("is_big_tech", False)

    badges = ""
    if job.get("is_funded"): badges += "💰 JUST RAISED  "
    if ng: badges += "🎓 NEW GRAD FRIENDLY  "
    if bt: badges += "⭐ BIG TECH"

    # Tap-to-track buttons (move the job between dashboard sections)
    kb = {"inline_keyboard": [[
        {"text": "✅ Applied",  "callback_data": f"a:{jid}"},
        {"text": "🗑 Dismiss",  "callback_data": f"d:{jid}"},
    ]]} if jid else None

    if reminder:
        send_telegram(
            f"⏰ <b>REMINDER — Applied yet?</b>\n\n"
            f"🎨 <b>{title}</b>\n"
            f"🏢 <b>{company}</b>\n"
            f"📍 {loc}\n\n"
            f"Posted ~7 mins ago. Early applicants get 3× more callbacks!\n\n"
            f'🔗 <a href="{url}">Apply Now →</a>',
            reply_markup=kb,
        )
    else:
        send_telegram(
            f"🚨 <b>NEW JOB — Act in 2 Minutes!</b>\n"
            + (f"{badges}\n" if badges else "") +
            f"\n🎨 <b>{title}</b>\n"
            f"🏢 <b>{company}</b>\n"
            f"📍 <b>{loc}</b>\n"
            f"💰 <b>{salary}</b>\n"
            f"🌐 <b>{source}</b>\n\n"
            f'🔗 <a href="{url}">View &amp; Apply Now →</a>\n\n'
            f"<i>⚡ Seen within 2 mins of posting!</i>",
            reply_markup=kb,
        )

# ─────────────────────────────────────────────────────────────────
#  🔘  TELEGRAM CALLBACKS — tap Applied / Dismiss to update dashboard
# ─────────────────────────────────────────────────────────────────
TG_API = lambda m: f"https://api.telegram.org/bot{CONFIG['TELEGRAM_BOT_TOKEN']}/{m}"

def update_status(jid: str, status: str):
    store = load_store()
    if jid in store:
        store[jid]["status"] = status
        store[jid]["applied_at"] = now_pt().isoformat() if status == "applied" else None
        save_store(store)
        return store[jid]
    return None

def _answer_callback(cqid: str, text: str = ""):
    try:
        requests.post(TG_API("answerCallbackQuery"),
                      json={"callback_query_id": cqid, "text": text}, timeout=10)
    except Exception as e:
        log.error(f"answerCallback: {e}")

def _mark_message(chat_id, msg_id, status):
    if not (chat_id and msg_id): return
    label = "✅ Applied" if status == "applied" else "🗑 Dismissed"
    try:
        requests.post(TG_API("editMessageReplyMarkup"),
                      json={"chat_id": chat_id, "message_id": msg_id,
                            "reply_markup": {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}},
                      timeout=10)
    except Exception as e:
        log.error(f"editMarkup: {e}")

def poll_telegram():
    """Short-poll getUpdates and apply any Applied/Dismiss button taps."""
    try:
        r = requests.get(TG_API("getUpdates"),
                         params={"offset": load_offset() + 1, "timeout": 0,
                                 "allowed_updates": json.dumps(["callback_query"])}, timeout=15)
        if r.status_code != 200:
            return
        changed = False
        for upd in r.json().get("result", []):
            save_offset(upd["update_id"])
            cq = upd.get("callback_query")
            if not cq:
                continue
            data    = cq.get("data", "")
            msg     = cq.get("message", {}) or {}
            chat_id = (msg.get("chat") or {}).get("id")
            msg_id  = msg.get("message_id")
            if ":" in data:
                action, jid = data.split(":", 1)
                status = {"a": "applied", "d": "dismissed"}.get(action)
                if status and update_status(jid, status):
                    changed = True
                    _answer_callback(cq["id"], "✅ Marked applied" if status == "applied" else "🗑 Dismissed")
                    _mark_message(chat_id, msg_id, status)
                    continue
            _answer_callback(cq["id"])
        if changed:
            publish_site()
    except Exception as e:
        log.error(f"poll_telegram: {e}")

# ─────────────────────────────────────────────────────────────────
#  🔎  JOBSPY SCRAPER
# ─────────────────────────────────────────────────────────────────
H = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def scrape_jobspy(query: str, location: str, sites=None) -> list:
    try:
        from jobspy import scrape_jobs
    except ImportError:
        log.error("JobSpy not installed! Run: pip3 install python-jobspy")
        return []

    if sites is None:
        sites = ["linkedin", "indeed"]   # Glassdoor (400) & ZipRecruiter (403) block scraping

    active = [s for s in sites if not is_cooling(s)]
    if not active:
        return []

    try:
        df = scrape_jobs(
            site_name=active,
            search_term=query,
            location=location,
            results_wanted=CONFIG["RESULTS_PER_SEARCH"],
            hours_old=CONFIG["HOURS_OLD"],
            country_indeed="USA",
            job_type="fulltime",
        )
        if df is None or df.empty:
            return []

        # JobSpy returns pandas NaN (a truthy float) for missing pay — guard
        # against it, else int(NaN) raises and the whole query's rows are lost.
        def _money(x):
            try:
                if x is None or (isinstance(x, float) and math.isnan(x)):
                    return None
                return int(x)
            except (ValueError, TypeError):
                return None

        jobs = []
        for _, row in df.iterrows():
            salary = "Not listed"
            lo = _money(row.get("min_amount"))
            hi = _money(row.get("max_amount"))
            if lo and hi:
                salary = f"${lo:,} – ${hi:,} / {row.get('interval','yr')}"
            elif lo:
                salary = f"${lo:,}+"

            job = {
                "title":    str(row.get("title", "")).strip(),
                "company":  str(row.get("company", "")).strip(),
                "location": str(row.get("location", location)).strip(),
                "url":      str(row.get("job_url", "")),
                "salary":   salary,
                "description": str(row.get("description", ""))[:400],
                "posted_at": str(row.get("date_posted", "Recently")),
                "source":   str(row.get("site", "")).title(),
            }
            if job["title"] and job["url"]:
                jobs.append(job)
        return jobs

    except Exception as e:
        err = str(e).lower()
        log.error(f"JobSpy [{query}@{location}]: {e}")
        if "429" in err or "rate" in err or "blocked" in err:
            if "linkedin" in err: set_cooldown("linkedin", 60)
            if "indeed"   in err: set_cooldown("indeed", 30)
            if "glassdoor" in err: set_cooldown("glassdoor", 45)
        return []

def scrape_rss(name: str, url: str, default_location="Remote") -> list:
    if is_cooling(name): return []
    jobs = []
    try:
        r = requests.get(url, headers=H, timeout=15)
        if r.status_code == 429: set_cooldown(name, 60); return []
        if r.status_code != 200: return []
        # feedparser tolerates real-world quirks (undefined entities, raw &,
        # custom namespaces) that the strict stdlib XML parser rejects.
        feed = feedparser.parse(r.content)
        for entry in feed.entries[:12]:
            title = (entry.get("title") or "").strip()
            link  = (entry.get("link") or "").strip()
            desc  = (entry.get("summary") or entry.get("description") or "").strip()
            company = "Unknown"
            if ": " in title and name == "WeWorkRemotely":
                parts = title.split(": ", 1)
                company, title = parts[0].strip(), parts[1].strip()
            else:
                company = (
                    (entry.get("author") or "").strip() or
                    (entry.get("company_name") or "").strip() or
                    "Unknown"
                )
            salary = "See posting"
            m = re.search(r'\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?', desc)
            if m: salary = m.group(0)
            jobs.append({
                "title": title, "company": company,
                "location": default_location, "url": link,
                "salary": salary,
                "description": re.sub(r"<[^>]+>", "", desc)[:300],
                "posted_at": "Recently", "source": name,
            })
    except Exception as e:
        log.error(f"RSS {name}: {e}")
    return jobs

RSS_FEEDS = [
    ("WeWorkRemotely", "https://weworkremotely.com/categories/remote-design-jobs.rss"),
    ("Dribbble",       "https://dribbble.com/jobs.rss?location=United+States"),
    ("AuthenticJobs",  "https://authenticjobs.com/feed/?type=4"),
    ("Coroflot",       "https://www.coroflot.com/jobs/rss?discipline=interaction_ux_ui"),
    # ── Added (verified working) ──
    ("NoDesk",         "https://nodesk.co/remote-jobs/design/index.xml"),
    ("RealWFA",        "https://www.realworkfromanywhere.com/remote-design-jobs/rss.xml"),
    ("RealWFA-Product","https://www.realworkfromanywhere.com/remote-product-jobs/rss.xml"),
    ("RemoteOK",       "https://remoteok.com/remote-design-jobs.rss"),
    ("Himalayas",      "https://himalayas.app/jobs/rss"),
    ("JobsCollider",   "https://jobscollider.com/remote-design-jobs.rss"),
    ("JobsCollider-Product", "https://jobscollider.com/remote-product-jobs.rss"),
    ("HackerNews",     "https://hnrss.org/newest?q=ux+designer"),
]

# ─────────────────────────────────────────────────────────────────
#  🌉  SF / BAY AREA + STARTUP SOURCES (custom scrapers)
# ─────────────────────────────────────────────────────────────────
# ── US-only location filter with priority tiers ──
#   1 = San Francisco · 2 = Bay Area · 3 = Seattle/LA/NY/Philly ·
#   4 = other US · 5 = US-remote · None = explicit foreign (excluded)
NON_US = [
    "india", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "pune",
    "chennai", "gurgaon", "noida", "kolkata", "ahmedabad",
    "dubai", "abu dhabi", "uae", "united arab emirates", "qatar", "doha",
    "saudi", "riyadh", "bahrain", "kuwait", "oman",
    "united kingdom", "england", "scotland", " uk", "u.k", "london", "manchester",
    "canada", "toronto", "vancouver", "montreal", "ottawa", "ontario", "calgary",
    "germany", "berlin", "munich", "hamburg", "france", "paris", "lyon",
    "netherlands", "amsterdam", "spain", "madrid", "barcelona", "portugal", "lisbon",
    "ireland", "dublin", "poland", "warsaw", "krakow", "romania", "bucharest", "ukraine",
    "italy", "rome", "milan", "sweden", "stockholm", "denmark", "copenhagen",
    "norway", "oslo", "finland", "helsinki", "switzerland", "zurich", "geneva",
    "austria", "vienna", "belgium", "brussels", "czech", "prague", "hungary", "budapest",
    "greece", "athens", "singapore", "australia", "sydney", "melbourne", "brisbane",
    "new zealand", "auckland", "brazil", "sao paulo", "mexico", "argentina",
    "colombia", "bogota", "chile", "peru", "japan", "tokyo", "china", "beijing",
    "shanghai", "hong kong", "taiwan", "south korea", "seoul",
    "pakistan", "nepal", "bangladesh", "sri lanka", "nigeria", "lagos", "kenya",
    "nairobi", "egypt", "cairo", "morocco", "tunisia", "ghana", "uzbekistan",
    "south africa", "philippines", "manila", "indonesia", "jakarta", "vietnam",
    "hanoi", "thailand", "bangkok", "malaysia", "kuala lumpur", "turkey", "türkiye",
    "istanbul", "israel", "tel aviv", "worldwide", "emea", "apac", "latam",
]
_P2_BAY = ["bay area", "oakland", "palo alto", "mountain view", "san jose",
           "sunnyvale", "berkeley", "menlo park", "redwood city", "santa clara",
           "south san francisco", "cupertino", "fremont", "emeryville", "san mateo"]
_P3_CITIES = ["seattle", "los angeles", "l.a.", "new york", "nyc", "manhattan",
              "brooklyn", "philadelphia", "philly"]
_US_STATE_RE = re.compile(
    r',\s*(a[klzr]|c[aot]|d[ce]|fl|ga|hi|i[adln]|k[sy]|la|m[adeinost]|n[cdehjmvy]|'
    r'o[hkr]|pa|ri|s[cd]|t[nx]|ut|v[at]|w[aivy])\b', re.I)

def location_rank(location: str):
    t = (location or "").lower()
    if any(tok in t for tok in NON_US):
        return None
    if "san francisco" in t:
        return 1
    if any(k in t for k in _P2_BAY):
        return 2
    if any(k in t for k in _P3_CITIES):
        return 3
    if "united states" in t or "usa" in t or re.search(r'\bu\.?s\.?a?\b', t) or _US_STATE_RE.search(t):
        return 4
    if "remote" in t:
        return 5
    return None

def is_us(location: str) -> bool:
    return location_rank(location) is not None

# ── Y Combinator (workatastartup.com) — real YC startups, structured JSON ──
def scrape_yc() -> list:
    if is_cooling("yc"): return []
    jobs = []
    try:
        r = requests.get("https://www.workatastartup.com/jobs/l/designer", headers=H, timeout=20)
        if r.status_code == 429: set_cooldown("yc", 60); return []
        if r.status_code != 200: return []
        m = re.search(r'data-page="([^"]+)"', r.text)
        if not m: return []
        data = json.loads(html.unescape(m.group(1)))
        for j in data.get("props", {}).get("jobs", []):
            company = (j.get("companyName") or "Unknown").strip()
            batch   = (j.get("companyBatch") or "").strip()
            jobs.append({
                "title":    (j.get("title") or "").strip(),
                "company":  f"{company} ({batch})" if batch else company,
                "location": (j.get("location") or "See posting").strip(),
                "url":      j.get("applyUrl") or "",
                "salary":   (j.get("salary") or "Not listed").strip(),
                "description": (j.get("companyOneLiner") or "")[:300],
                "posted_at": "Recently", "source": "Y Combinator",
            })
    except Exception as e:
        log.error(f"YC: {e}")
    return jobs

# ── OpenDoors Careers — public Supabase REST API (filtered to SF/Bay/Remote) ──
OPENDOORS_API = "https://jpshpibjgrxvcbnpapyq.supabase.co/rest/v1/jobs"
OPENDOORS_KEY = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Impwc2hw"
                 "aWJqZ3J4dmNibnBhcHlxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzA1NDU3MzEsImV4cCI6MjA4"
                 "NjEyMTczMX0.O-tgJ-mB3guaIhtOOzyHIF-dgqMLGhvliaTWR9W7HAY")
def scrape_opendoors() -> list:
    if is_cooling("opendoors"): return []
    jobs = []
    try:
        r = requests.get(
            OPENDOORS_API,
            params={"select": "title,company_name,city,country,work_type,description,apply_url",
                    "status": "eq.published"},
            headers={"apikey": OPENDOORS_KEY, "Authorization": f"Bearer {OPENDOORS_KEY}",
                     "Accept": "application/json"}, timeout=20)
        if r.status_code == 429: set_cooldown("opendoors", 60); return []
        if r.status_code != 200: return []
        for j in r.json():
            wt   = (j.get("work_type") or "").lower()
            city = (j.get("city") or "").strip()
            ctry = (j.get("country") or "").strip()
            if "remote" in wt:
                loc = f"Remote ({city})" if city else "Remote"
            else:
                loc = ", ".join(p for p in [city, ctry] if p) or "See posting"
            if not is_us(loc):
                continue
            jobs.append({
                "title":    (j.get("title") or "").strip(),
                "company":  (j.get("company_name") or "Unknown").strip(),
                "location": loc,
                "url":      j.get("apply_url") or "",
                "salary":   "Not listed",
                "description": re.sub(r"<[^>]+>", "", j.get("description") or "")[:300],
                "posted_at": "Recently", "source": "OpenDoors",
            })
    except Exception as e:
        log.error(f"OpenDoors: {e}")
    return jobs

# ── Built In SF — design/UX jobs via server-rendered JSON-LD ItemList ──
def scrape_builtinsf() -> list:
    if is_cooling("builtin"): return []
    jobs = []
    try:
        r = requests.get("https://www.builtinsf.com/jobs/design-ux", headers=H, timeout=20)
        if r.status_code == 429: set_cooldown("builtin", 60); return []
        if r.status_code != 200: return []
        page = html.unescape(r.text)
        for block in re.findall(r'<script type="application/ld[^"]*json">(.*?)</script>', page, re.S):
            try:
                data = json.loads(block)
            except Exception:
                continue
            graph = data.get("@graph", []) if isinstance(data, dict) else []
            for node in graph:
                if not isinstance(node, dict) or node.get("@type") != "ItemList":
                    continue
                for el in node.get("itemListElement", []):
                    title = (el.get("name") or "").strip()
                    url   = (el.get("url") or "").strip()
                    if not (title and url):
                        continue
                    jobs.append({
                        "title": title, "company": "See posting",
                        "location": "San Francisco Bay Area, CA",
                        "url": url, "salary": "Not listed",
                        "description": (el.get("description") or "")[:300],
                        "posted_at": "Recently", "source": "BuiltIn SF",
                    })
    except Exception as e:
        log.error(f"BuiltIn SF: {e}")
    return jobs

# ── UIUXJobsBoard — design-only board, React-Router turbo-stream payload ──
def _turbo_decode(arr, node, depth=0):
    if depth > 8: return None
    if isinstance(node, dict):
        out = {}
        for k, vi in node.items():
            key = arr[int(k[1:])] if isinstance(k, str) and k.startswith("_") else k
            out[key] = _turbo_decode(arr, arr[vi], depth+1) if isinstance(vi, int) and 0 <= vi < len(arr) else vi
        return out
    if isinstance(node, list):
        return [_turbo_decode(arr, arr[e], depth+1) if isinstance(e, int) and 0 <= e < len(arr) else e for e in node]
    return node

def scrape_uiuxjobsboard() -> list:
    if is_cooling("uiux"): return []
    jobs = []
    try:
        r = requests.get("https://uiuxjobsboard.com/design-jobs.data", headers=H, timeout=20)
        if r.status_code == 429: set_cooldown("uiux", 60); return []
        if r.status_code != 200: return []
        arr = json.loads(r.text)
        # Locate the jobs array: a list of int refs whose first item decodes to a job dict.
        refs = None
        for cand in arr:
            if isinstance(cand, list) and cand and all(isinstance(x, int) for x in cand):
                test = _turbo_decode(arr, arr[cand[0]]) if 0 <= cand[0] < len(arr) else None
                if isinstance(test, dict) and "title" in test and "slug" in test:
                    refs = cand; break
        if not refs: return []
        for idx in refs[:40]:
            j = _turbo_decode(arr, arr[idx])
            if not isinstance(j, dict): continue
            comp = j.get("company") or {}
            city = (j.get("city") or "").strip()
            loc  = "Remote" if j.get("remote") else (city or (j.get("country") or "").strip() or "See posting")
            if not is_us(loc): continue
            jobs.append({
                "title":    (j.get("title") or "").strip(),
                "company":  (comp.get("name") if isinstance(comp, dict) else "") or "Unknown",
                "location": loc,
                "url":      f"https://uiuxjobsboard.com/job/{j.get('slug','')}",
                "salary":   (j.get("salary") or "Not listed").strip(),
                "description": "",
                "posted_at": j.get("timeAgo", "Recently"),
                "source": "UIUXJobsBoard",
            })
    except Exception as e:
        log.error(f"UIUXJobsBoard: {e}")
    return jobs

# ── startups.gallery — curated startups; pull live roles from their ATS APIs ──
def _greenhouse_jobs(co: str) -> list:
    out = []
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{co}/jobs", headers=H, timeout=15)
        if r.status_code != 200: return []
        for j in r.json().get("jobs", []):
            loc = ((j.get("location") or {}).get("name") or "").strip()
            out.append({
                "title":    (j.get("title") or "").strip(),
                "company":  (j.get("company_name") or co).strip(),
                "location": loc or "See posting",
                "url":      j.get("absolute_url") or "",
                "salary":   "Not listed", "description": "",
                "posted_at": "Recently", "source": "Startups.Gallery",
            })
    except Exception as e:
        log.error(f"Greenhouse {co}: {e}")
    return out

def _ashby_jobs(co: str) -> list:
    out = []
    try:
        r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{co}", headers=H, timeout=15)
        if r.status_code != 200: return []
        for j in r.json().get("jobs", []):
            loc = "Remote" if j.get("isRemote") else (j.get("location") or "See posting")
            out.append({
                "title":    (j.get("title") or "").strip(),
                "company":  co.replace("-", " ").title(),
                "location": loc,
                "url":      j.get("jobUrl") or j.get("applyUrl") or "",
                "salary":   "Not listed",
                "description": (j.get("descriptionPlain") or "")[:300],
                "posted_at": "Recently", "source": "Startups.Gallery",
            })
    except Exception as e:
        log.error(f"Ashby {co}: {e}")
    return out

def scrape_startups_gallery() -> list:
    if is_cooling("startupsgallery"): return []
    jobs = []
    try:
        r = requests.get("https://startups.gallery/jobs", headers=H, timeout=20)
        if r.status_code == 429: set_cooldown("startupsgallery", 60); return []
        if r.status_code != 200: return []
        gh  = set(re.findall(r'greenhouse\.io/([A-Za-z0-9_.-]+)/jobs/', r.text))
        ash = set(re.findall(r'ashbyhq\.com/([A-Za-z0-9_.-]+)/', r.text))
        for co in list(gh)[:25]:
            jobs.extend(_greenhouse_jobs(co)); time.sleep(0.5)
        for co in list(ash)[:25]:
            jobs.extend(_ashby_jobs(co)); time.sleep(0.5)
        jobs = [j for j in jobs if is_us(j["location"])]
    except Exception as e:
        log.error(f"Startups.Gallery: {e}")
    return jobs

# ═════════════════════════════════════════════════════════════════
#  💰  FUNDING RADAR — fresh raises = design hire incoming
#  Scans VC news + SEC Form D, then for each freshly-funded company
#  checks its Greenhouse/Ashby board for OPEN DESIGN ROLES. Matched
#  roles are injected into the job board; the raise itself is alerted
#  to a separate funding channel and shown in the "Just Raised" tab.
# ═════════════════════════════════════════════════════════════════
# a16z / Sequoia / First Round don't expose a working RSS feed (404 / 403),
# so we follow each via a Google News query instead — this actually surfaces
# the funding rounds they lead, not just their blog posts.
def _gnews(query: str) -> str:
    return ("https://news.google.com/rss/search?q="
            f"{requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en")

FUNDING_FEEDS = [
    # ── Core tech/VC press (verified working) ──
    ("TechCrunch Venture",  "https://techcrunch.com/category/venture/feed/"),
    ("TechCrunch Startups", "https://techcrunch.com/category/startups/feed/"),
    ("TechCrunch Funding",  "https://techcrunch.com/tag/funding/feed/"),
    ("VentureBeat",         "https://venturebeat.com/category/business/feed/"),
    ("Crunchbase News",     "https://news.crunchbase.com/feed/"),
    ("StrictlyVC",          "https://strictlyvc.com/feed/"),
    ("GeekWire Funding",    "https://www.geekwire.com/tag/funding/feed/"),
    ("YC Blog",             "https://www.ycombinator.com/blog/rss.xml"),
    ("Fortune",             "https://fortune.com/feed/"),
    ("SiliconANGLE",        "https://siliconangle.com/feed/"),
    ("Axios",               "https://api.axios.com/feed/"),
    # ── Funding-specific sources (added) ──
    ("Tech Funding News",   "https://techfundingnews.com/feed/"),
    ("TechStartups",        "https://techstartups.com/feed/"),
    ("AlleyWatch",          "https://www.alleywatch.com/feed/"),
    ("SaaStr",              "https://www.saastr.com/feed/"),
    ("The SaaS News",       "https://thesaasnews.com/feed"),
    # ── VC firms followed via Google News (no usable native RSS) ──
    ("a16z (news)",         _gnews('"Andreessen Horowitz" (raises OR funding OR "series") when:7d')),
    ("Sequoia (news)",      _gnews('"Sequoia Capital" (raises OR funding OR "series") when:7d')),
    ("First Round (news)",  _gnews('"First Round Capital" (raises OR funding OR "series") when:7d')),
    # ── Broad early-stage funding sweep (catches raises no single outlet covers) ──
    ("Funding Sweep (news)", _gnews('startup ("raises" OR "raised") ("seed" OR "series a" OR "series b") when:2d')),
]

AMOUNT_RE = re.compile(r'\$\s*([\d,.]+)\s*(billion|million|B|M)\b', re.IGNORECASE)
STAGE_RE  = re.compile(r'\b(pre-?seed|seed|series\s+[a-f]|bridge|extension)\b', re.IGNORECASE)
STAGE_PRIORITY = {
    "pre-seed": 10, "preseed": 10, "seed": 9,
    "series a": 8, "series b": 7, "series c": 6,
    "series d": 5, "bridge": 6, "extension": 5,
}
TIER1_VCS = {
    "a16z", "andreessen", "sequoia", "benchmark", "greylock", "accel",
    "kleiner", "lightspeed", "general catalyst", "founders fund",
    "index ventures", "y combinator", "ycombinator", "first round",
    "bessemer", "spark capital", "thrive capital", "khosla", "lux capital", "coatue",
}
FUNDING_SKIP_SECTORS = [
    "biotech", "pharma", "drug", "clinical", "medical device",
    "aerospace", "defense", "military", "mining", "agriculture",
]
FUNDING_WORDS = [
    "raises", "raised", "funding", "investment", "round",
    "backed", "seed", "series", "capital", "million", "billion",
]

def extract_funding(text: str) -> dict:
    result = {"amount": None, "stage": None, "investors": None, "priority": 3}
    m = AMOUNT_RE.search(text)
    if m:
        num  = float(m.group(1).replace(",", ""))
        unit = m.group(2).lower()
        result["amount"] = f"${num}B" if unit in ("billion", "b") else f"${num}M"
    m = STAGE_RE.search(text)
    if m:
        stage = m.group(0).lower().strip()
        result["stage"]    = stage.title()
        result["priority"] = STAGE_PRIORITY.get(stage, 3)
    inv_m = re.search(r'(?:led by|backed by|investors?[:\s]+)([\w\s,]+?)(?:\.|,\s+\w+\s+said|\n)',
                      text, re.IGNORECASE)
    if inv_m:
        investors = inv_m.group(1).strip().rstrip(",")
        result["investors"] = investors
        if any(t in investors.lower() for t in TIER1_VCS):
            result["priority"] += 3
    return result

def funding_is_relevant(title: str, description: str) -> bool:
    text = f"{title} {description}".lower()
    if not any(w in text for w in FUNDING_WORDS):
        return False
    if any(s in text for s in FUNDING_SKIP_SECTORS):
        return False
    return True

# Narrow set = "this segment is the funding sentence" (for ':' splits).
_FUNDVERB_RE = re.compile(
    r'\b(raises?|raised|secures?|secured|closes?|closed|lands?|nabs?|bags?|'
    r'snags?|scores?|hauls?|nets?|pulls?|funding|round|backed|invests?|investment)\b', re.I)
# Broad set = "the company name ends here" (where to cut the title).
_CUT_RE = re.compile(
    r'\b(raises?|raised|secures?|secured|closes?|closed|lands?|nabs?|bags?|snags?|'
    r'scores?|hauls?|nets?|pulls?|gets?|gains?|announces?|launch(?:es|ed)?|unveils?|'
    r'debuts?|invests?|seeks?|seeking|locks?|emerges?|is|are|was|were|eyeing|eyes|'
    r'says?|to|valued?|hits?|reaches?|after|with|for|on)\b', re.I)
_SEP_RE = re.compile(r'\s+[-–—|]\s+')   # " - Publisher" / "Company – descriptor"
# "Seattle startup Emphere" / "Oslo-based AI startup Mimir" → the name follows "startup".
_DESCRIPTOR_RE = re.compile(r'\bstartups?\b\s+(.+)$', re.I)

def _clean_company(title: str) -> str:
    """Pull a clean company name out of a headline, incl. Google News titles
    like 'Co raises $X led by VC - Publisher' or 'Lead-in: Co raises $X'."""
    t = (title or "").strip()
    t = _SEP_RE.split(t)[0]                       # drop trailing " - Publisher" / descriptors
    if ":" in t:                                  # "Editorial lead-in: Company raises ..."
        segs = [s.strip() for s in t.split(":") if s.strip()]
        verby = [s for s in segs if _FUNDVERB_RE.search(s)]
        t = verby[0] if verby else segs[-1]
    dm = _DESCRIPTOR_RE.search(t)                 # strip "City/AI startup <Name>" lead-in
    if dm and dm.group(1) and not _CUT_RE.match(dm.group(1)):
        t = dm.group(1)
    m = _CUT_RE.search(t)
    if m:
        t = t[:m.start()]
    t = t.split(",")[0].strip(" –—-:•·[](){}").strip()
    return t or (title or "").split(",")[0].strip()

# A roundup/editorial headline isn't a single company — skip these.
_ROUNDUP_RE = re.compile(
    r'\b(funding wrap|wrap|weekly|this week|week in|roundup|round-up|recap|digest|'
    r'report|rises?|grew|grows|list of|top \d|deals?|acquisitions?|edition|frenzy|'
    r'race|investments?|takes the bulk)\b', re.I)

def _is_company_like(name: str) -> bool:
    """Heuristic: does this look like a real company name vs. a news headline?"""
    n = (name or "").strip()
    if not (2 <= len(n) <= 40):           return False
    if re.match(r'^\d', n):               return False   # "30", "3 top VCs"
    if any(c in n for c in "%[]{}"):      return False
    if len(n.split()) > 6:                return False
    if _ROUNDUP_RE.search(n):             return False
    if n.lower().endswith(("startup", "startups", "founder", "founders",
                           "ventures", "partners", "capital")):
        return False                                     # descriptor / VC firm, not a raiser
    if n.lower() == n and " " in n:       return False   # all-lowercase multiword ≠ a name
    return True

def scrape_funding_rss(name: str, url: str) -> list:
    if is_cooling(name): return []
    items = []
    try:
        r = requests.get(url, headers=H, timeout=15)
        if r.status_code == 429: set_cooldown(name, 60); return []
        if r.status_code != 200: return []
        feed = feedparser.parse(r.content)
        for entry in feed.entries[:20]:
            title = (entry.get("title") or "").strip()
            link  = (entry.get("link") or "").strip()
            desc  = re.sub(r"<[^>]+>", "", (entry.get("summary") or entry.get("description") or "")).strip()
            if not funding_is_relevant(title, desc):
                continue
            company = _clean_company(title)
            if not _is_company_like(company):     # skip roundups / non-company headlines
                continue
            f = extract_funding(f"{title} {desc}")
            items.append({
                "company":   company,
                "amount":    f["amount"],
                "stage":     f["stage"],
                "investors": f["investors"],
                "source":    name,
                "url":       link,
                "priority":  f["priority"],
            })
    except Exception as e:
        log.error(f"Funding RSS {name}: {e}")
    return items

def fetch_sec_edgar() -> list:
    if is_cooling("sec"): return []
    items = []
    try:
        today = now_pt().strftime("%Y-%m-%d")
        r = requests.get(
            "https://efts.sec.gov/LATEST/search-index?q=%22Form+D%22"
            f"&dateRange=custom&startdt={today}&enddt={today}&forms=D",
            headers={**H, "Accept": "application/json"}, timeout=20)
        if r.status_code != 200: return []
        for hit in r.json().get("hits", {}).get("hits", [])[:20]:
            src     = hit.get("_source", {})
            company = src.get("entity_name", "Unknown")
            raw     = src.get("total_offering_amount", 0)
            if raw and raw < 1_000_000: continue
            amount  = f"${raw/1_000_000:.1f}M" if raw else None
            items.append({
                "company":   company,
                "amount":    amount,
                "stage":     "SEC Form D Filing",
                "investors": "See filing",
                "source":    "SEC EDGAR",
                "url":       "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                             f"&company={requests.utils.quote(company)}&type=D",
                "priority":  3,
            })
    except Exception as e:
        log.error(f"SEC EDGAR: {e}")
    return items

# ── Enrichment: does this freshly-funded company have open design roles? ──
_CO_SUFFIX_RE = re.compile(r'\b(inc|llc|ltd|corp|co|technologies|technology|labs|ai|io|app)\b\.?',
                           re.IGNORECASE)
def _ats_slugs(company: str):
    base = re.sub(r'\([^)]*\)', '', company).strip().lower()      # drop "(YC W24)"
    base = _CO_SUFFIX_RE.sub('', base)
    words = re.sub(r'[^a-z0-9 ]', '', base).split()
    if not words: return []
    cands = ["".join(words), words[0]]
    if len(words) > 1:
        cands.append("-".join(words))
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c); out.append(c)
    return out

def find_company_design_roles(company: str) -> list:
    """Best-effort: try the company's Greenhouse/Ashby board for US design roles."""
    found = []
    for slug in _ats_slugs(company)[:2]:        # cap lookups per company
        for fetch in (_greenhouse_jobs, _ashby_jobs):
            try:
                for j in fetch(slug):
                    if not j.get("title") or not j.get("url"):
                        continue
                    if not is_us(j.get("location", "")):
                        continue
                    if not classify(j["title"], j.get("company", ""), j.get("description", "")).get("relevant"):
                        continue
                    found.append(j)
            except Exception:
                pass
            time.sleep(0.3)
        if found:
            break
    # de-dupe by url
    uniq, seen = [], set()
    for j in found:
        if j["url"] not in seen:
            seen.add(j["url"]); uniq.append(j)
    return uniq[:6]

def funding_id(company, amount):
    return hashlib.md5(f"{(company or '').lower()}|{amount or ''}".encode()).hexdigest()

def notify_funding(item: dict, roles: list = None, reminder: bool = False):
    company   = item.get("company", "Unknown")
    amount    = item.get("amount") or "Undisclosed"
    stage     = item.get("stage") or "?"
    investors = item.get("investors") or "Undisclosed"
    source    = item.get("source", "")
    url       = item.get("url", "")
    priority  = item.get("priority", 0)
    roles     = roles or []

    tier1 = "⭐ TIER 1 VC  " if priority >= 8  else ""
    hot   = "💥 HOT  "      if priority >= 10 else ""

    roles_block = ""
    if roles:
        lines = "\n".join(f'• <a href="{r["url"]}">{r["title"]}</a> — {r.get("location","")}' for r in roles)
        roles_block = f"\n\n🎯 <b>{len(roles)} open design role(s):</b>\n{lines}"

    if reminder:
        send_funding(
            f"⏰ <b>REMINDER — Reached out yet?</b>\n\n"
            f"💰 <b>{company}</b> raised <b>{amount}</b>\n"
            f"Stage: {stage}  |  Investors: {investors}\n\n"
            f"Fresh raise = design hire incoming. Contact the founder!{roles_block}\n\n"
            f'🔗 <a href="{url}">Read More →</a>'
        )
    else:
        send_funding(
            f"💰 <b>NEW FUNDING ALERT!</b>\n{hot}{tier1}\n\n"
            f"🏢 <b>{company}</b>\n"
            f"💵 <b>Raised:</b> {amount}\n"
            f"📈 <b>Stage:</b> {stage}\n"
            f"👥 <b>Investors:</b> {investors}\n"
            f"📰 <b>Source:</b> {source}{roles_block}\n\n"
            f'🔗 <a href="{url}">Read Full Story →</a>\n\n'
            f"💡 <i>Fresh raise = design hiring mode. Reach out within 48 hrs!</i>"
        )

def publish_funding():
    try:
        store = load_json(CONFIG["FUNDING_STORE_FILE"], {})
        published = [v for v in store.values() if v.get("status") != "dismissed"]
        published.sort(key=lambda f: f.get("first_seen", ""), reverse=True)
        os.makedirs(CONFIG["SITE_DIR"], exist_ok=True)
        save_json(CONFIG["FUNDING_WEB_FILE"], published)
    except Exception as e:
        log.error(f"publish_funding: {e}")

def run_funding_check(job_seen: set, job_store: dict, job_pending: list,
                      jobs_silent: bool) -> int:
    """Scan funding sources, enrich with open design roles, alert + inject.
    Mutates the passed job state in place; returns the count of new raises."""
    if not funding_enabled():
        return 0
    log.info(f"💰 Funding check {now_pt().strftime('%H:%M:%S %Z')}")
    f_seen    = set(load_json(CONFIG["SEEN_FUNDING_FILE"], []))
    f_store   = load_json(CONFIG["FUNDING_STORE_FILE"], {})
    f_pending = load_json(CONFIG["PENDING_FUNDING_FILE"], [])
    f_silent  = not os.path.exists("funding_backfill_done.flag")

    raises = []
    for name, url in FUNDING_FEEDS:
        raises.extend(scrape_funding_rss(name, url)); time.sleep(0.5)
    raises.extend(fetch_sec_edgar())
    raises.sort(key=lambda x: x.get("priority", 0), reverse=True)

    new_count = 0
    for item in raises:
        company = item.get("company", "")
        amount  = item.get("amount", "")
        if not company:
            continue
        fid = funding_id(company, amount)
        if fid in f_seen:
            continue
        f_seen.add(fid)
        new_count += 1

        roles = find_company_design_roles(company)
        # Inject matched design roles into the job board (they're real openings)
        for r in roles:
            jid = job_id(r["title"], r.get("company", company), r.get("location", ""))
            if jid in job_seen:
                continue
            job_seen.add(jid)
            rank = location_rank(r.get("location", "")) or 4
            flags = classify(r["title"], r.get("company", ""), r.get("description", ""))
            first_seen = (now_pt() - timedelta(hours=CONFIG["NEW_HOURS"] + 1)) if jobs_silent else now_pt()
            job_store[jid] = {
                "id": jid, "title": r["title"], "company": r.get("company", company),
                "location": r.get("location", ""), "salary": r.get("salary", "Not listed"),
                "url": r.get("url", ""), "source": f"💰 {company} (just raised)",
                "is_new_grad": bool(flags.get("is_new_grad")),
                "is_big_tech": bool(flags.get("is_big_tech")),
                "is_funded": True,
                "funding_note": f"{company} raised {amount or 'a round'}",
                "posted_at": "Recently", "priority": rank,
                "first_seen": first_seen.isoformat(), "status": "active", "applied_at": None,
            }
            if not jobs_silent:
                notify({**r, "is_funded": True}, jid=jid)
                job_pending.append({
                    "job": r,
                    "remind_at": (now_pt() + timedelta(minutes=CONFIG["REMINDER_MINUTES"])).isoformat(),
                })
                time.sleep(1)

        if not f_silent:
            log.info(f"💰 {company} — {amount} [{item.get('source')}] · {len(roles)} role(s)")
            notify_funding(item, roles)
            f_pending.append({
                "item": item,
                "remind_at": (now_pt() + timedelta(minutes=CONFIG["REMINDER_MINUTES"])).isoformat(),
            })
            time.sleep(1)

        f_store[fid] = {
            "id": fid, "company": company, "amount": amount or "Undisclosed",
            "stage": item.get("stage") or "?", "investors": item.get("investors") or "Undisclosed",
            "source": item.get("source", ""), "url": item.get("url", ""),
            "priority": item.get("priority", 0),
            "roles": [{"title": r["title"], "url": r["url"], "location": r.get("location", "")} for r in roles],
            "first_seen": (now_pt() - timedelta(hours=CONFIG["NEW_HOURS"] + 1)).isoformat() if f_silent else now_pt().isoformat(),
            "status": "active",
        }

    # Funding reminders
    still = []
    for p in f_pending:
        due = datetime.fromisoformat(p["remind_at"])
        if due.tzinfo is None: due = due.replace(tzinfo=TZ)
        if now_pt() >= due:
            notify_funding(p["item"], reminder=True)
        else:
            still.append(p)

    save_json(CONFIG["SEEN_FUNDING_FILE"], list(f_seen))
    save_json(CONFIG["PENDING_FUNDING_FILE"], still)
    save_json(CONFIG["FUNDING_STORE_FILE"], f_store)
    publish_funding()
    if f_silent:
        open("funding_backfill_done.flag", "w").close()
        log.info(f"🔇 Funding backfill: seeded {new_count} raises (no Telegram alerts).")
    else:
        log.info(f"✅ {new_count} new raises." if new_count else "😴 No new funding.")
    return new_count

# ─────────────────────────────────────────────────────────────────
#  🌐  WEBSITE — data only. The page lives in docs/index.html + style.css
#  + app.js (hand-authored, committed once). Python writes ONLY the data
#  file docs/jobs.json — that file is the single link between bot and site.
# ─────────────────────────────────────────────────────────────────
def git_publish():
    if not os.path.isdir(".git"):
        return  # repo/remote not set up yet — nothing to publish to
    try:
        subprocess.run(["git", "add", CONFIG["SITE_DIR"]], capture_output=True)
        # Only commit/push when something in docs/ actually changed
        if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
            subprocess.run(["git", "commit", "-m", "\U0001F4CA Update job dashboard data"], capture_output=True)
            push = subprocess.run(["git", "push"], capture_output=True, text=True)
            if push.returncode == 0:
                log.info("\U0001F4E4 Dashboard published to GitHub")
            else:
                log.warning(f"git push failed (set up the remote/auth): {push.stderr[:120]}")
    except FileNotFoundError:
        log.warning("git not found \u2014 skipping publish")
    except Exception as e:
        log.error(f"git_publish: {e}")

def publish_site():
    try:
        store = load_store()
        # Website shows everything except dismissed jobs; newest first
        published = [v for v in store.values() if v.get("status") != "dismissed"]
        published.sort(key=lambda j: j.get("first_seen", ""), reverse=True)
        os.makedirs(CONFIG["SITE_DIR"], exist_ok=True)
        save_json(CONFIG["WEB_FILE"], published)
        if CONFIG.get("PUBLISH_TO_GIT"):
            git_publish()
    except Exception as e:
        log.error(f"publish_site: {e}")

# ─────────────────────────────────────────────────────────────────
#  🔄  MAIN CHECK
# ─────────────────────────────────────────────────────────────────
def run_check():
    log.info(f"🔍 Job check {now_pt().strftime('%H:%M:%S %Z')}")
    seen    = load_seen()
    pending = load_pending()
    store   = load_store()
    # Clean the existing board: drop non-US / too-senior jobs and (re)tag priority
    for _jid in list(store.keys()):
        _rec  = store[_jid]
        _rank = location_rank(_rec.get("location", ""))
        if _rank is None or not classify(_rec.get("title", ""), _rec.get("company", "")).get("relevant"):
            del store[_jid]
        else:
            _rec["priority"] = _rank
    new_count = 0
    all_jobs  = []

    # JobSpy — all major boards
    for query in SEARCH_QUERIES:
        for loc in LOCATIONS:
            all_jobs.extend(scrape_jobspy(query, loc))
            time.sleep(2)

    # RSS design boards
    for name, url in RSS_FEEDS:
        all_jobs.extend(scrape_rss(name, url))
        time.sleep(1)

    # SF / Bay Area + startup sources
    all_jobs.extend(scrape_yc())
    all_jobs.extend(scrape_opendoors())
    all_jobs.extend(scrape_builtinsf())
    all_jobs.extend(scrape_uiuxjobsboard())
    all_jobs.extend(scrape_startups_gallery())

    # First ever run = SILENT backfill: seed the board with the current
    # backlog (aged into "Yet to Apply") without blasting Telegram. A flag
    # file marks it done, so every later run alerts new jobs normally.
    silent = not os.path.exists("backfill_done.flag")

    # Process
    for job in all_jobs:
        if not job.get("title") or not job.get("url"):
            continue
        flags = classify(job.get("title",""), job.get("company",""), job.get("description",""))
        if not flags["relevant"]:
            continue
        job.update(flags)
        rank = location_rank(job.get("location", ""))
        if rank is None:
            continue  # not in the USA — skip
        jid = job_id(job["title"], job.get("company",""), job.get("location",""))
        if jid in seen:
            continue
        seen.add(jid)
        new_count += 1
        # backfilled jobs are aged so they land in "Yet to Apply", not "New"
        first_seen = (now_pt() - timedelta(hours=CONFIG["NEW_HOURS"] + 1)) if silent else now_pt()
        store[jid] = {
            "id":          jid,
            "title":       job["title"],
            "company":     job.get("company", "Unknown"),
            "location":    job.get("location", ""),
            "salary":      job.get("salary", "Not listed"),
            "url":         job.get("url", ""),
            "source":      job.get("source", ""),
            "is_new_grad": bool(job.get("is_new_grad")),
            "is_big_tech": bool(job.get("is_big_tech")),
            "posted_at":   job.get("posted_at", "Recently"),
            "priority":    rank,
            "first_seen":  first_seen.isoformat(),
            "status":      "active",
            "applied_at":  None,
        }
        if not silent:
            log.info(f"🆕 {job['title']} @ {job.get('company')} [{job.get('source')}]")
            notify(job, jid=jid)
            pending.append({
                "job": job,
                "remind_at": (now_pt() + timedelta(minutes=CONFIG["REMINDER_MINUTES"])).isoformat(),
            })
            time.sleep(1)

    # 💰 Funding radar — fresh raises + the design roles they're hiring for.
    # Mutates seen/store/pending in place (injects matched roles as job cards).
    run_funding_check(seen, store, pending, jobs_silent=silent)

    # Reminders — skip jobs already applied/dismissed from Telegram
    still = []
    for item in pending:
        j    = item["job"]
        rjid = job_id(j["title"], j.get("company", ""), j.get("location", ""))
        if store.get(rjid, {}).get("status") in ("applied", "dismissed"):
            continue
        due = datetime.fromisoformat(item["remind_at"])
        if due.tzinfo is None: due = due.replace(tzinfo=TZ)
        if now_pt() >= due:
            notify(j, reminder=True, jid=rjid)
        else:
            still.append(item)

    save_seen(seen)
    save_pending(still)
    save_store(store)
    publish_site()
    if silent:
        open("backfill_done.flag", "w").close()
        log.info(f"🔇 Silent backfill: seeded {new_count} jobs to the board (no Telegram alerts).")
    else:
        log.info(f"✅ {new_count} new jobs." if new_count else "😴 No new jobs this cycle.")

# ─────────────────────────────────────────────────────────────────
#  💓  HEARTBEAT + DAILY DIGEST
# ─────────────────────────────────────────────────────────────────
def heartbeat():
    send_telegram(f"💓 Job Bot alive @ {now_pt().strftime('%H:%M %Z')}")

def daily_digest():
    send_telegram(
        f"☀️ <b>Morning Shruty!</b> Job Bot is running 🤖\n\n"
        f"📅 {now_pt().strftime('%A, %B %d, %Y')}\n"
        f"🎯 {len(SEARCH_QUERIES)} search queries active\n"
        f"🌐 LinkedIn · Indeed · Glassdoor · ZipRecruiter\n"
        f"   + Remotive · Dribbble · WeWorkRemotely + more\n"
        f"🏢 {len(BIG_TECH)} big tech companies monitored\n"
        + (f"💰 {len(FUNDING_FEEDS)} funding feeds + SEC Form D → design-role radar\n" if funding_enabled() else "")
        + f"\n<i>🎓 Graduating May 2026 — let's get that offer!</i>"
    )

# ─────────────────────────────────────────────────────────────────
#  🚀  START
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("=" * 60)
    log.info("  🎨 JOB BOT — Starting")
    log.info("=" * 60)

    try:
        import jobspy
        log.info("✅ JobSpy ready.")
    except ImportError:
        log.error("❌ Run: pip3 install python-jobspy"); exit(1)

    send_telegram(
        f"🎨 <b>Job Bot is LIVE!</b>\n\n"
        f"⚡ First alert: <b>2 min</b> after posting\n"
        f"⏰ Reminder: <b>7 min</b>\n"
        f"💓 Heartbeat: every hour\n\n"
        f"🌐 Sources: LinkedIn · Indeed · Glassdoor\n"
        f"   ZipRecruiter · Remotive · Dribbble\n"
        f"   WeWorkRemotely · Jobicy + more\n\n"
        f"🎓 <b>New Grad + Mid Level</b> roles\n"
        f"🏠 Remote · Hybrid · On-site Bay Area\n\n"
        + (f'📊 <a href="https://{CONFIG["GITHUB_USER"]}.github.io/{CONFIG["GITHUB_REPO"]}/">Your job dashboard</a>\n'
           f"   Tap ✅/🗑 on alerts to sort jobs\n\n" if CONFIG["GITHUB_USER"] else "") +
        f"<i>Graduating May 2026 — let's get that offer! 🚀</i>"
    )

    if funding_enabled():
        send_funding(
            f"💰 <b>Funding Radar is LIVE!</b>\n\n"
            f"📡 {len(FUNDING_FEEDS)} VC news feeds + SEC Form D\n"
            f"🎯 Each fresh raise → I check the company's careers board "
            f"for open design roles and push them to your job board.\n\n"
            f"<i>Fresh raise = design hire incoming. Reach out within 48 hrs! 🚀</i>"
        )

    run_check()
    schedule.every(CONFIG["POLL_INTERVAL_MINUTES"]).minutes.do(run_check)
    schedule.every(CONFIG["HEARTBEAT_HOURS"]).hours.do(heartbeat)
    schedule.every().day.at(f"{CONFIG['DAILY_DIGEST_HOUR']:02d}:00").do(daily_digest)

    log.info(f"⏱ Polling every {CONFIG['POLL_INTERVAL_MINUTES']} min.")
    while True:
        schedule.run_pending()
        poll_telegram()   # apply any Applied/Dismiss button taps
        time.sleep(30)
