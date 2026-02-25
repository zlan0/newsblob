"""
GhanaFront v2 — RSS Scraper Bot
- Supports PocketBase (free, self-hosted) and Supabase
- Saves full article content (500-1000 words via extraction)
- Sets articles as 'pending' for admin review/AI rewrite
- Runs every 5 minutes via schedule
- Can also auto-publish without review if AUTO_PUBLISH_SCRAPES=true
"""

import hashlib, os, time, logging, asyncio
from datetime import datetime, timezone
from typing import Optional
import feedparser
import httpx
from bs4 import BeautifulSoup
import schedule
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

DB_BACKEND = os.environ.get("DB_BACKEND", "supabase")
POCKETBASE_URL = os.environ.get("POCKETBASE_URL", "http://localhost:8090")
POCKETBASE_ADMIN_EMAIL = os.environ.get("POCKETBASE_ADMIN_EMAIL", "admin@ghanafront.com")
POCKETBASE_ADMIN_PASSWORD = os.environ.get("POCKETBASE_ADMIN_PASSWORD", "admin123456")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Set to "true" to skip admin review and auto-publish all scraped articles
AUTO_PUBLISH_SCRAPES = os.environ.get("AUTO_PUBLISH_SCRAPES", "false").lower() == "true"

# ─── RSS Feeds ────────────────────────────────────────────────────────────────

RSS_FEEDS = [
    # Ghana
    {"name": "CitiNews",          "url": "https://citinewsroom.com/feed/",                        "region": "ghana"},
    {"name": "JoyOnline",         "url": "https://www.myjoyonline.com/feed/",                      "region": "ghana"},
    {"name": "GhanaWeb",          "url": "https://www.ghanaweb.com/GhanaHomePage/rss/index.php",   "region": "ghana"},
    {"name": "Graphic Online",    "url": "https://www.graphic.com.gh/feed/rss",                    "region": "ghana"},
    {"name": "GhanaBusinessNews", "url": "https://www.ghanabusinessnews.com/feed/",                "region": "ghana"},
    {"name": "Pulse Ghana",       "url": "https://www.pulse.com.gh/rss",                          "region": "ghana"},
    {"name": "Adom Online",       "url": "https://adomonline.com/feed/",                           "region": "ghana"},
    # Africa / Global
    {"name": "BBC Africa",        "url": "http://feeds.bbci.co.uk/news/world/africa/rss.xml",      "region": "africa"},
    {"name": "Al Jazeera",        "url": "https://www.aljazeera.com/xml/rss/all.xml",              "region": "global"},
]

# ─── Category Keywords ────────────────────────────────────────────────────────

CATEGORIES = {
    "politics": {
        "strong": ["election","parliament","president","prime minister","government","minister","ndc","npp",
                   "akufo-addo","mahama","ballot","constituency","lawmaker","legislature","coup","cabinet",
                   "referendum","opposition","ruling party"," mp "," mps ","member of parliament"],
        "weak": ["vote","campaign","governance","regulation","law","bill passed","corruption","protest"],
    },
    "business": {
        "strong": ["economy","cedi","ghana stock exchange","gse","investment","gdp","inflation",
                   "bank of ghana","imf","world bank","trade","revenue","tax","fiscal","monetary",
                   "interest rate","stock","bond","finance minister","budget","debt","forex","export"],
        "weak": ["business","market","profit","loss","revenue","growth","economic","financial","billion","million"],
    },
    "sports": {
        "strong": ["black stars","ghana football","gfa","premier league ghana","afcon","world cup",
                   "olympics","asante kotoko","hearts of oak","transfer","match","tournament","champion",
                   "trophy","fifa","caf ","coach","manager"],
        "weak": ["sports","football","soccer","league","club","player","team","score","fixture","game"],
    },
    "tech": {
        "strong": ["artificial intelligence"," ai ","machine learning","blockchain","cryptocurrency",
                   "bitcoin","fintech","cybersecurity","5g","tech startup","google","apple ","microsoft",
                   "cloud computing","developer","open source"],
        "weak": ["technology","digital","mobile","internet","innovation","platform","cyber","software"],
    },
    "health": {
        "strong": ["hospital","disease","covid","malaria","clinic","vaccine","outbreak","epidemic",
                   "pandemic","surgery","diagnosis","treatment","medicine","doctor","nurse",
                   "ghana health service","ministry of health","nhis","public health","hiv","aids"],
        "weak": ["health","medical","wellness","nutrition","drug","pharmacy","clinical","therapy"],
    },
    "entertainment": {
        "strong": ["music video","album","concert","award show","grammy","ghana music awards","vgma",
                   "afrobeats","hiplife","highlife","movie","film","actor","actress","celebrity",
                   "sarkodie","stonebwoy","kuami eugene","shatta wale","medikal","black sherif"],
        "weak": ["entertainment","music","arts","culture","festival","performance","release"],
    },
    "world": {
        "strong": ["united nations","un security council","nato","european union","white house",
                   "us president","russia","ukraine","israel","iran","china ","north korea","trump",
                   "sanctions","treaty","diplomacy","g7","g20","refugee","war crimes","ceasefire"],
        "weak": ["international","global","world","usa","europe","washington","london","paris"],
    },
}
MIN_SCORE = 2

def categorize(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    scores = {}
    for cat, kw in CATEGORIES.items():
        s = sum(3 for k in kw.get("strong",[]) if k in text)
        s += sum(1 for k in kw.get("weak",[]) if k in text)
        scores[cat] = s
    best = max(scores, key=scores.get)
    return best if scores[best] >= MIN_SCORE else "general"

def title_hash(title: str) -> str:
    return hashlib.md5(title.strip().lower().encode()).hexdigest()

def trending_score(views: int, shares: int, hours_old: float) -> float:
    return 0.6 * views + 0.3 * shares + 0.1 / max(hours_old, 0.1)

def extract_image(entry) -> Optional[str]:
    if hasattr(entry, "media_content") and entry.media_content:
        return entry.media_content[0].get("url")
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if "image" in enc.get("type",""):
                return enc.get("href") or enc.get("url")
    if hasattr(entry, "summary"):
        soup = BeautifulSoup(entry.summary, "html.parser")
        img = soup.find("img")
        if img and img.get("src"): return img["src"]
    return None

def fetch_full_article(url: str, timeout: int = 10) -> str:
    """Try to fetch full article content from the article URL."""
    if not url: return ""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": "GhanaFrontBot/2.0"}) as client:
            r = client.get(url)
            if r.status_code != 200: return ""
            soup = BeautifulSoup(r.text, "html.parser")
            # Remove nav, ads, footer
            for tag in soup.find_all(["nav","footer","aside","script","style","header","figure"]):
                tag.decompose()
            # Try common article containers
            for selector in ["article", ".article-body", ".post-content", ".entry-content",
                              ".story-body", ".article-content", "main", "#content"]:
                el = soup.select_one(selector)
                if el:
                    text = el.get_text(separator="\n", strip=True)
                    if len(text.split()) > 80:
                        return text[:5000]  # cap at 5000 chars
            # Fallback: get all paragraphs
            paras = soup.find_all("p")
            text = "\n".join(p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 40)
            return text[:5000]
    except Exception as e:
        log.debug(f"Full fetch failed for {url}: {e}")
        return ""

# ─── DB Helpers ───────────────────────────────────────────────────────────────

_pb_token = None

def pb_get_token():
    global _pb_token
    r = httpx.post(f"{POCKETBASE_URL}/api/admins/auth-with-password",
        json={"identity": POCKETBASE_ADMIN_EMAIL, "password": POCKETBASE_ADMIN_PASSWORD})
    if r.status_code == 200:
        _pb_token = r.json().get("token")
    return _pb_token

def pb_headers():
    if not _pb_token: pb_get_token()
    return {"Authorization": _pb_token or ""}

def already_exists(thash: str) -> bool:
    if DB_BACKEND == "pocketbase":
        try:
            r = httpx.get(f"{POCKETBASE_URL}/api/collections/articles/records",
                params={"filter": f'title_hash="{thash}"', "perPage": 1},
                headers=pb_headers())
            return r.json().get("totalItems", 0) > 0
        except: return False
    else:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        r = sb.table("articles").select("id").eq("title_hash", thash).execute()
        return len(r.data) > 0

def insert_article(data: dict):
    if DB_BACKEND == "pocketbase":
        r = httpx.post(f"{POCKETBASE_URL}/api/collections/articles/records",
            json=data, headers=pb_headers())
        if r.status_code not in (200, 201):
            log.error(f"PB insert failed: {r.text[:200]}")
    else:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        sb.table("articles").insert(data).execute()

def update_trending_scores():
    log.info("Updating trending scores...")
    if DB_BACKEND == "pocketbase":
        try:
            r = httpx.get(f"{POCKETBASE_URL}/api/collections/articles/records",
                params={"filter": 'status="published"', "perPage": 500, "sort": "-published_at"},
                headers=pb_headers())
            arts = r.json().get("items", [])
            for a in arts:
                try:
                    pub = datetime.fromisoformat(a["published_at"].replace("Z","+00:00"))
                    hours_old = max((datetime.now(timezone.utc)-pub).total_seconds()/3600, 0.01)
                    score = trending_score(a.get("views",0), a.get("shares",0), hours_old)
                    httpx.patch(f"{POCKETBASE_URL}/api/collections/articles/records/{a['id']}",
                        json={"trending_score": score}, headers=pb_headers())
                except: pass
        except Exception as e:
            log.error(f"Trending score update failed: {e}")
    else:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        arts = sb.table("articles").select("id,views,shares,published_at").execute().data
        for a in arts:
            try:
                pub = datetime.fromisoformat(a["published_at"].replace("Z","+00:00"))
                hours_old = max((datetime.now(timezone.utc)-pub).total_seconds()/3600, 0.01)
                score = trending_score(a.get("views",0), a.get("shares",0), hours_old)
                sb.table("articles").update({"trending_score": score}).eq("id", a["id"]).execute()
            except: pass
    log.info("Trending scores updated.")

# ─── Core Scrape ─────────────────────────────────────────────────────────────

def scrape_all_feeds():
    log.info("Starting RSS scrape cycle...")
    new_count = 0
    status = "published" if AUTO_PUBLISH_SCRAPES else "pending"

    for feed_meta in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_meta["url"])
            log.info(f"[{feed_meta['name']}] {len(feed.entries)} entries found")

            for entry in feed.entries[:25]:
                title = entry.get("title","").strip()
                if not title: continue

                thash = title_hash(title)
                if already_exists(thash): continue

                # Get RSS summary
                rss_summary = BeautifulSoup(
                    entry.get("summary", entry.get("description","")), "html.parser"
                ).get_text()[:800]

                # Try to fetch full article content
                url = entry.get("link","")
                full_content = fetch_full_article(url) if url else ""

                # Use full content if substantial, else RSS summary
                content = full_content if len(full_content.split()) > 100 else rss_summary
                summary = rss_summary[:400] if rss_summary else content[:400]

                published_raw = entry.get("published_parsed") or entry.get("updated_parsed")
                if published_raw:
                    published_at = datetime(*published_raw[:6], tzinfo=timezone.utc).isoformat()
                else:
                    published_at = datetime.now(timezone.utc).isoformat()

                image_url = extract_image(entry)
                category = categorize(title, summary)

                hours_old = max(
                    (datetime.now(timezone.utc) - datetime.fromisoformat(
                        published_at.replace("Z","+00:00"))).total_seconds()/3600, 0.01)

                article = {
                    "title": title,
                    "title_hash": thash,
                    "content": content,
                    "summary": summary,
                    "url": url,
                    "image_url": image_url or "",
                    "source": feed_meta["name"],
                    "region": feed_meta["region"],
                    "category": category,
                    "published_at": published_at,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "views": 0, "shares": 0,
                    "trending_score": trending_score(0, 0, hours_old),
                    "status": status,
                    "is_original": False,
                    "ai_rewritten": False,
                }

                insert_article(article)
                new_count += 1
                log.info(f"  ✓ [{category}][{status}] {title[:60]}")

        except Exception as e:
            log.error(f"[{feed_meta['name']}] Error: {e}")

    log.info(f"Cycle complete. {new_count} new articles. Status: {status}")
    return new_count

# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("GhanaFront Scraper Bot v2 starting...")
    if DB_BACKEND == "pocketbase":
        log.info(f"Using PocketBase at {POCKETBASE_URL}")
        pb_get_token()
    else:
        log.info("Using Supabase")

    scrape_all_feeds()
    update_trending_scores()

    schedule.every(5).minutes.do(scrape_all_feeds)
    schedule.every(1).hours.do(update_trending_scores)

    while True:
        schedule.run_pending()
        time.sleep(30)
