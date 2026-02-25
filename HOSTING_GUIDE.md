# GhanaFront v2 — Complete Free Hosting & Deployment Guide

## Overview: 100% Free Stack (No Credit Card Required)

| Layer | Tool | Free Tier | Notes |
|-------|------|-----------|-------|
| Frontend | Vercel / Netlify | Unlimited | Drag & drop deploy |
| Backend API | Railway.app | $5 credit/month (always free) | Auto-deploy from GitHub |
| Database | PocketBase on Fly.io | Free tier | OR use Supabase free |
| Scraper | Railway (same as backend) | Included | Runs every 5 min |
| AI Rewriting | OpenRouter.ai | Free models | mistral-7b-instruct:free |
| Domain | Freenom / Cloudflare | Free | .com.gh costs ~$10/yr |

---

## OPTION A: PocketBase + Railway (Recommended — Simplest)

### Step 1: Deploy PocketBase Database (Fly.io — Free)

PocketBase is a single Go binary with a built-in SQLite database. 
No Supabase, no PostgreSQL, no paid tier for essential features.

```bash
# Install flyctl (Fly.io CLI)
curl -L https://fly.io/install.sh | sh

# Login / Sign up (free)
flyctl auth login

# Create a new Fly.io app for PocketBase
mkdir pocketbase-ghana && cd pocketbase-ghana

# Create fly.toml
cat > fly.toml << 'EOF'
app = "ghanafront-db"
primary_region = "jnb"  # Johannesburg — closest to Ghana

[build]
  image = "ghcr.io/muchobien/pocketbase:latest"

[mounts]
  source = "pb_data"
  destination = "/pb_data"

[http_service]
  internal_port = 8090
  force_https = true
  auto_stop_machines = false
  auto_start_machines = true

[[vm]]
  memory = "256mb"
  cpu_kind = "shared"
  cpus = 1
EOF

flyctl launch --no-deploy
flyctl volumes create pb_data --size 1  # 1GB free volume
flyctl deploy

# Get your PocketBase URL
# Visit: https://ghanafront-db.fly.dev/_/
# Set up admin account on first visit
```

After deploying, go to https://ghanafront-db.fly.dev/_/ and create your admin account.

**Create the 'articles' collection in PocketBase:**
Go to Collections → New Collection → name it "articles" → add these fields:
- title (text, required)
- title_hash (text, required, unique)
- content (text, large)
- summary (text)
- url (url)
- image_url (url)
- source (text)
- region (text, default: ghana)
- category (text, default: general)
- status (select: pending, published, draft, reviewed; default: pending)
- is_original (bool, default: false)
- ai_rewritten (bool, default: false)
- published_at (date)
- views (number, default: 0)
- shares (number, default: 0)
- trending_score (number, default: 0)

Set API rules: List/View = public, Create/Update/Delete = admin only.

---

### Step 2: Deploy Backend + Scraper (Railway.app — Free)

Railway gives $5/month free credit — enough for 24/7 operation.

1. Go to railway.app and sign up with GitHub
2. Click "New Project" → "Deploy from GitHub repo"
3. Push your project to GitHub first:
   ```bash
   git init && git add . && git commit -m "GhanaFront v2"
   git remote add origin https://github.com/YOUR_USERNAME/ghanafront.git
   git push -u origin main
   ```
4. In Railway: select your repo → set Root Directory to `backend`
5. Add Environment Variables in Railway dashboard:
   ```
   DB_BACKEND=pocketbase
   POCKETBASE_URL=https://ghanafront-db.fly.dev
   POCKETBASE_ADMIN_EMAIL=admin@ghanafront.com
   POCKETBASE_ADMIN_PASSWORD=your-password
   ADMIN_SECRET=your-secret-here
   OPENROUTER_API_KEY=sk-or-your-key
   AUTO_PUBLISH_SCRAPES=false
   ```
6. Railway auto-detects Python and deploys. Your API will be at:
   `https://ghanafront-backend.up.railway.app`

**Also create a second Railway service for the scraper:**
Same repo → Root Directory: `backend` → Start Command: `python rss_scraper.py`
This runs the scraper 24/7 automatically — no cron job needed.

---

### Step 3: Deploy Frontend (Vercel — Free Forever)

1. Go to vercel.com → New Project → Import GitHub repo
2. Framework: Other (static site)
3. No build command needed
4. Deploy. Your site will be at `https://ghanafront.vercel.app`

**Connect frontend to backend:**
After deploying, open your site and run in browser console:
```js
localStorage.setItem('gf_api', 'https://ghanafront-backend.up.railway.app')
localStorage.setItem('gf_admin_secret', 'your-secret-here')
```

Or hardcode in `js/app.js`:
```js
const API_BASE = 'https://ghanafront-backend.up.railway.app';
```

---

## OPTION B: Supabase (Free Tier)

Supabase free tier: 500MB DB, 2GB bandwidth, 50MB file storage.
Key limitations: paused after 1 week inactivity (free tier), limited row-level access.

1. Go to supabase.com → Create project
2. Paste `backend/schema.sql` into the SQL editor and run it
3. Get your URL and anon key from Settings → API
4. Set in Railway env vars:
   ```
   DB_BACKEND=supabase
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-key
   ```

---

## OPTION C: All Local (for testing)

```bash
# Install PocketBase
wget https://github.com/pocketbase/pocketbase/releases/latest/download/pocketbase_linux_amd64.zip
unzip pocketbase_linux_amd64.zip
./pocketbase serve

# In another terminal: run backend
cd backend
pip install -r requirements.txt
cp .env.example .env  # edit with your values
uvicorn main:app --reload --port 8000

# In another terminal: run scraper
python rss_scraper.py

# Open frontend
open ../index.html  # or use python3 -m http.server 3000
```

---

## AI Article Rewriting Setup (Free)

1. Go to openrouter.ai → Sign up (free)
2. Get API key from dashboard
3. Free models include: `mistralai/mistral-7b-instruct:free`
4. Add to your .env: `OPENROUTER_API_KEY=sk-or-...`

The AI rewrites scraped articles from ~200 words (RSS summary) to 600-900 words
of original, unique content — meeting Google AdSense and Adsterra content requirements.

---

## Automatic RSS Scraping

The scraper runs every 5 minutes automatically once deployed on Railway.
It:
1. Fetches latest articles from all RSS feeds
2. Tries to extract full article content from source URLs  
3. Saves articles with status "pending" (or "published" if AUTO_PUBLISH_SCRAPES=true)
4. Admin reviews pending articles, optionally AI-rewrites them, then approves

To add new RSS feeds: edit `backend/rss_scraper.py` → `RSS_FEEDS` list, or use the
Admin Panel → Scraper Config tab.

---

## Getting AdSense / Adsterra Approved

Google AdSense and Adsterra require:
✅ Original content (not copied) — use AI Rewrite feature
✅ 600+ words per article — AI Rewrite produces 600-900 words
✅ Privacy Policy page — add `/pages/privacy.html`  
✅ About page — add `/pages/about.html`
✅ Contact page — add `/pages/contact.html`
✅ At least 20-30 published articles before applying
✅ Clean, professional design — GhanaFront has this
✅ No copyright violations — AI rewrites ensure originality

**Adsterra** is easier to get approved than AdSense and works well with news sites.
Sign up at adsterra.com after you have 20+ articles live.

---

## Custom Domain

1. Buy domain at namecheap.com (~$10-15/year) or use Cloudflare Registrar (at cost)
2. In Vercel: Settings → Domains → Add your domain
3. Update DNS at your registrar to point to Vercel
4. SSL is automatic and free

---

## 7-Day Launch Checklist

| Day | Task |
|-----|------|
| 1 | Deploy PocketBase on Fly.io, create articles collection |
| 2 | Deploy backend + scraper on Railway |
| 3 | Deploy frontend on Vercel, connect to backend |
| 4 | Set API URL in admin panel, trigger first scrape |
| 5 | Review scraped articles, AI rewrite 20-30, publish |
| 6 | Submit sitemap to Google Search Console |
| 7 | Apply for Adsterra (easier than AdSense, faster approval) |

After 30 days of content: Apply for Google AdSense.
