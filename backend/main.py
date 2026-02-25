"""
GhanaFront v2 — FastAPI Backend
Supports: PocketBase (free, self-hosted) OR Supabase
AI-powered article rewriting via OpenRouter (free tier available)
Admin endpoints: post articles, approve scraped articles
Auto-publish with AI rewrite for AdSense/Adsterra compliance
"""

from fastapi import FastAPI, Query, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os, httpx, hashlib, logging
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="GhanaFront API v2", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── Database Backend Selection ───────────────────────────────────────────────
# DB_BACKEND=pocketbase  → free, self-hostable at fly.io or railway.app free tier
# DB_BACKEND=supabase    → supabase.com free tier
DB_BACKEND = os.environ.get("DB_BACKEND", "supabase")

POCKETBASE_URL = os.environ.get("POCKETBASE_URL", "http://localhost:8090")
POCKETBASE_ADMIN_EMAIL = os.environ.get("POCKETBASE_ADMIN_EMAIL", "admin@ghanafront.com")
POCKETBASE_ADMIN_PASSWORD = os.environ.get("POCKETBASE_ADMIN_PASSWORD", "admin123456")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "ghanafront-admin-secret-change-me")

# OpenRouter for free AI rewriting (openrouter.ai — free models available)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
AI_REWRITE_MODEL = os.environ.get("AI_REWRITE_MODEL", "mistralai/mistral-7b-instruct:free")

# ─── DB Client Abstraction ────────────────────────────────────────────────────

_pb_token = None

async def pb_auth():
    global _pb_token
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{POCKETBASE_URL}/api/admins/auth-with-password",
            json={"identity": POCKETBASE_ADMIN_EMAIL, "password": POCKETBASE_ADMIN_PASSWORD})
        if r.status_code == 200:
            _pb_token = r.json().get("token")
    return _pb_token

async def pb_headers():
    if not _pb_token:
        await pb_auth()
    return {"Authorization": _pb_token or ""}

async def db_get_articles(category=None, region=None, sort="trending", page=1, limit=20, status="published"):
    offset = (page - 1) * limit
    if DB_BACKEND == "pocketbase":
        headers = await pb_headers()
        filters = [f'status="{status}"']
        if category and category != "all": filters.append(f'category="{category}"')
        if region and region != "all": filters.append(f'region="{region}"')
        filter_str = " && ".join(filters)
        sort_map = {"trending": "-trending_score", "recent": "-published_at", "views": "-views"}
        sort_field = sort_map.get(sort, "-trending_score")
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{POCKETBASE_URL}/api/collections/articles/records",
                params={"filter": filter_str, "sort": sort_field, "page": page, "perPage": limit},
                headers=headers)
            data = r.json()
            return data.get("items", [])
    else:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        q = sb.table("articles").select("*")
        if status != "all": q = q.eq("status", status)
        if category and category != "all": q = q.eq("category", category)
        if region and region != "all": q = q.eq("region", region)
        sort_map = {"trending": ("trending_score", True), "recent": ("published_at", True), "views": ("views", True)}
        col, desc = sort_map.get(sort, ("trending_score", True))
        q = q.order(col, desc=desc).range(offset, offset + limit - 1)
        return q.execute().data or []

async def db_get_article(article_id: str):
    if DB_BACKEND == "pocketbase":
        headers = await pb_headers()
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{POCKETBASE_URL}/api/collections/articles/records/{article_id}", headers=headers)
            if r.status_code == 200: return r.json()
            return None
    else:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        r = sb.table("articles").select("*").eq("id", article_id).single().execute()
        return r.data

async def db_update_article(article_id: str, data: dict):
    if DB_BACKEND == "pocketbase":
        headers = await pb_headers()
        async with httpx.AsyncClient() as client:
            await client.patch(f"{POCKETBASE_URL}/api/collections/articles/records/{article_id}",
                json=data, headers=headers)
    else:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        sb.table("articles").update(data).eq("id", article_id).execute()

async def db_insert_article(data: dict):
    if DB_BACKEND == "pocketbase":
        headers = await pb_headers()
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{POCKETBASE_URL}/api/collections/articles/records",
                json=data, headers=headers)
            return r.json()
    else:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        r = sb.table("articles").insert(data).execute()
        return r.data[0] if r.data else {}

async def db_search_articles(query: str, limit: int = 10):
    if DB_BACKEND == "pocketbase":
        headers = await pb_headers()
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{POCKETBASE_URL}/api/collections/articles/records",
                params={"filter": f'(title~"{query}"||summary~"{query}")&&status="published"',
                        "sort": "-trending_score", "perPage": limit},
                headers=headers)
            return r.json().get("items", [])
    else:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        r = sb.rpc("search_articles", {"query": query, "result_limit": limit}).execute()
        return r.data or []

# ─── Admin Auth ───────────────────────────────────────────────────────────────

def verify_admin(x_admin_secret: str = Header(None)):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(403, "Forbidden: Invalid admin secret")
    return True

# ─── AI Rewrite ───────────────────────────────────────────────────────────────

async def ai_rewrite_article(title: str, original_content: str) -> str:
    """Rewrite article to 600-900 words via OpenRouter free AI."""
    if not OPENROUTER_API_KEY:
        log.warning("No OPENROUTER_API_KEY — skipping AI rewrite")
        return original_content

    prompt = f"""You are a professional Ghanaian news journalist. Rewrite this news article to be:
- 600 to 900 words long (REQUIRED)
- 100% original and unique (important for Google AdSense/Adsterra approval)
- Clear, engaging journalistic English
- Factually accurate to the original story
- Has a strong intro paragraph, detailed body, and a conclusion
- Uses fresh, unique language — NOT copied from the source

HEADLINE: {title}

ORIGINAL:
{original_content}

Write ONLY the rewritten article body (no title or meta):"""

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post("https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                         "HTTP-Referer": "https://ghanafront.com",
                         "X-Title": "GhanaFront News"},
                json={"model": AI_REWRITE_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 1200})
            result = r.json()
            return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error(f"AI rewrite failed: {e}")
        return original_content

# ─── Models ───────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str

class PostArticleRequest(BaseModel):
    title: str
    content: str
    summary: Optional[str] = None
    category: str = "general"
    region: str = "ghana"
    image_url: Optional[str] = None
    source: str = "GhanaFront Staff"
    tags: Optional[List[str]] = []
    auto_publish: bool = True
    ai_expand: bool = False

class ApproveArticleRequest(BaseModel):
    article_id: str
    ai_rewrite: bool = False
    auto_publish: bool = True

# ─── Public Routes ────────────────────────────────────────────────────────────

@app.get("/api/articles")
async def get_articles(
    category: Optional[str] = None, region: Optional[str] = None,
    sort: str = "trending", page: int = 1, limit: int = 20):
    articles = await db_get_articles(category, region, sort, page, limit)
    return {"articles": articles, "page": page, "limit": limit}

@app.get("/api/articles/{article_id}")
async def get_article(article_id: str):
    article = await db_get_article(article_id)
    if not article: raise HTTPException(404, "Article not found")
    await db_update_article(article_id, {"views": (article.get("views") or 0) + 1})
    return article

@app.post("/api/articles/{article_id}/share")
async def share_article(article_id: str):
    article = await db_get_article(article_id)
    if not article: raise HTTPException(404, "Article not found")
    await db_update_article(article_id, {"shares": (article.get("shares") or 0) + 1})
    return {"ok": True}

@app.get("/api/search")
async def search(q: str = Query(..., min_length=2), limit: int = 10):
    results = await db_search_articles(q, limit)
    return {"results": results}

@app.get("/api/trending")
async def get_trending(limit: int = 10):
    articles = await db_get_articles(sort="trending", limit=limit)
    return articles

@app.get("/api/categories")
def get_categories():
    return {"categories": ["politics","business","sports","tech","health","entertainment","world","general"]}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    articles = await db_search_articles(req.query, 5)
    if not articles:
        return {"answer": f"I couldn't find recent news about '{req.query}'. Try browsing our categories.", "sources": []}
    top = articles[0]
    return {
        "answer": f"Here's what I found about '{req.query}': {top.get('summary','')} — reported by {top.get('source','')}.",
        "sources": [{"title": a["title"], "url": a.get("url",""), "source": a.get("source","")} for a in articles[:3]]
    }

@app.get("/api/sitemap")
async def sitemap():
    articles = await db_get_articles(sort="recent", limit=1000)
    return [{"id": a.get("id"), "published_at": a.get("published_at")} for a in articles]

@app.get("/health")
def health():
    return {"status": "ok", "db_backend": DB_BACKEND, "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/api/status")
async def api_status():
    articles = await db_get_articles(sort="recent", limit=10)
    return {
        "article_count": len(articles),
        "last_scrape": articles[0].get("created_at") if articles else None,
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ─── Admin Routes ─────────────────────────────────────────────────────────────

@app.get("/api/admin/scraped")
async def get_scraped_articles(page: int = 1, limit: int = 50, _=Depends(verify_admin)):
    """Get scraped articles pending review in admin panel."""
    articles = await db_get_articles(sort="recent", page=page, limit=limit, status="pending")
    return {"articles": articles, "page": page, "limit": limit}

@app.post("/api/admin/approve")
async def approve_article(req: ApproveArticleRequest, _=Depends(verify_admin)):
    """Approve a scraped article, optionally AI-rewrite it first."""
    article = await db_get_article(req.article_id)
    if not article: raise HTTPException(404, "Article not found")

    content = article.get("content") or article.get("summary") or ""
    ai_rewritten = False
    if req.ai_rewrite and content:
        log.info(f"AI rewriting: {article['title'][:60]}")
        content = await ai_rewrite_article(article["title"], content)
        ai_rewritten = True

    await db_update_article(req.article_id, {
        "status": "published" if req.auto_publish else "reviewed",
        "content": content,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "ai_rewritten": ai_rewritten
    })
    return {"ok": True, "article_id": req.article_id, "ai_rewritten": ai_rewritten}

@app.post("/api/admin/approve-bulk")
async def approve_bulk(article_ids: List[str], ai_rewrite: bool = False, _=Depends(verify_admin)):
    """Bulk approve multiple scraped articles."""
    results = []
    for aid in article_ids:
        try:
            article = await db_get_article(aid)
            if not article: continue
            content = article.get("content") or article.get("summary") or ""
            if ai_rewrite and content:
                content = await ai_rewrite_article(article["title"], content)
            await db_update_article(aid, {
                "status": "published", "content": content,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "ai_rewritten": ai_rewrite
            })
            results.append({"id": aid, "ok": True})
        except Exception as e:
            results.append({"id": aid, "ok": False, "error": str(e)})
    return {"results": results}

@app.delete("/api/admin/articles/{article_id}")
async def delete_article(article_id: str, _=Depends(verify_admin)):
    if DB_BACKEND == "pocketbase":
        headers = await pb_headers()
        async with httpx.AsyncClient() as client:
            await client.delete(f"{POCKETBASE_URL}/api/collections/articles/records/{article_id}", headers=headers)
    else:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        sb.table("articles").delete().eq("id", article_id).execute()
    return {"ok": True}

@app.post("/api/admin/post-article")
async def post_article(req: PostArticleRequest, _=Depends(verify_admin)):
    """Admin manually posts a news article with optional AI expansion."""
    content = req.content
    if req.ai_expand or len(content.split()) < 100:
        log.info(f"AI expanding admin article: {req.title[:50]}")
        content = await ai_rewrite_article(req.title, content)

    summary = req.summary or " ".join(content.split()[:50]) + "..."
    thash = hashlib.md5(req.title.strip().lower().encode()).hexdigest()

    article = {
        "title": req.title,
        "title_hash": thash,
        "content": content,
        "summary": summary,
        "category": req.category,
        "region": req.region,
        "image_url": req.image_url or "",
        "source": req.source,
        "status": "published" if req.auto_publish else "draft",
        "views": 0, "shares": 0, "trending_score": 0,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_original": True,
        "ai_rewritten": req.ai_expand,
        "url": "",
    }
    result = await db_insert_article(article)
    return {"ok": True, "article": result}

@app.post("/api/admin/scrape")
async def trigger_scrape(_=Depends(verify_admin)):
    """Manually trigger RSS scrape cycle from admin panel."""
    import threading
    result = {"error": None}
    def do_scrape():
        try:
            import sys
            sys.path.insert(0, os.path.dirname(__file__))
            from rss_scraper import scrape_all_feeds
            scrape_all_feeds()
        except Exception as e:
            result["error"] = str(e)
    t = threading.Thread(target=do_scrape, daemon=True)
    t.start()
    t.join(timeout=30)
    return {"ok": result["error"] is None, "error": result["error"]}

@app.get("/api/admin/status")
async def admin_status(_=Depends(verify_admin)):
    published = await db_get_articles(sort="recent", limit=500, status="published")
    pending = await db_get_articles(sort="recent", limit=500, status="pending")
    return {
        "published_count": len(published),
        "pending_count": len(pending),
        "db_backend": DB_BACKEND,
        "ai_enabled": bool(OPENROUTER_API_KEY),
        "ai_model": AI_REWRITE_MODEL if OPENROUTER_API_KEY else "disabled",
        "last_check": datetime.now(timezone.utc).isoformat()
    }
