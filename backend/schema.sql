-- GhanaFront v2 — Database Schema
-- Works with Supabase (paste into SQL editor)
-- For PocketBase: use the pocketbase_setup.json instead

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── Articles ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS articles (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  title         TEXT NOT NULL,
  title_hash    TEXT UNIQUE NOT NULL,
  content       TEXT,                          -- full article body (500-1000 words)
  summary       TEXT,                          -- short excerpt for cards
  url           TEXT NOT NULL DEFAULT '',
  image_url     TEXT DEFAULT '',
  source        TEXT NOT NULL,
  region        TEXT DEFAULT 'ghana',
  category      TEXT DEFAULT 'general',
  status        TEXT DEFAULT 'pending',        -- pending | published | draft | reviewed
  is_original   BOOLEAN DEFAULT FALSE,         -- true = admin-posted, false = scraped
  ai_rewritten  BOOLEAN DEFAULT FALSE,         -- true = AI has rewritten this
  published_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  views         INTEGER DEFAULT 0,
  shares        INTEGER DEFAULT 0,
  trending_score FLOAT DEFAULT 0,
  affiliates    JSONB DEFAULT '{}',
  seo_score     INTEGER DEFAULT 0
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_articles_category      ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_region        ON articles(region);
CREATE INDEX IF NOT EXISTS idx_articles_published     ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_trending      ON articles(trending_score DESC);
CREATE INDEX IF NOT EXISTS idx_articles_status        ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_title_trgm    ON articles USING gin(title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_articles_summary_trgm  ON articles USING gin(summary gin_trgm_ops);

-- ─── Sources ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sources (
  id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name       TEXT NOT NULL,
  rss_url    TEXT NOT NULL UNIQUE,
  region     TEXT DEFAULT 'ghana',
  is_active  BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Search Function ──────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION search_articles(query TEXT, result_limit INT DEFAULT 10)
RETURNS TABLE (
  id UUID, title TEXT, summary TEXT, content TEXT, url TEXT,
  image_url TEXT, source TEXT, category TEXT,
  published_at TIMESTAMPTZ, trending_score FLOAT
)
LANGUAGE sql AS $$
  SELECT id, title, summary, content, url, image_url, source, category,
         published_at, trending_score
  FROM articles
  WHERE status = 'published'
    AND (title ILIKE '%' || query || '%' OR summary ILIKE '%' || query || '%')
  ORDER BY trending_score DESC, published_at DESC
  LIMIT result_limit;
$$;

-- ─── Row Level Security ───────────────────────────────────────────────────────

ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
CREATE POLICY IF NOT EXISTS "Published articles readable"
  ON articles FOR SELECT USING (status = 'published');

-- ─── Sample RSS Seeds ─────────────────────────────────────────────────────────

INSERT INTO sources (name, rss_url, region) VALUES
  ('CitiNews',       'https://citinewsroom.com/feed/',                        'ghana'),
  ('JoyOnline',      'https://www.myjoyonline.com/feed/',                     'ghana'),
  ('GhanaWeb',       'https://www.ghanaweb.com/GhanaHomePage/rss/index.php',  'ghana'),
  ('Graphic Online', 'https://www.graphic.com.gh/feed/rss',                   'ghana'),
  ('BBC Africa',     'http://feeds.bbci.co.uk/news/world/africa/rss.xml',     'africa'),
  ('Al Jazeera',     'https://www.aljazeera.com/xml/rss/all.xml',             'global')
ON CONFLICT (rss_url) DO NOTHING;
