"""
AI News Fetcher
- Pulls from RSS feeds (direct + RSSHub)
- Deduplicates via database unique constraints + content hash
- Writes raw articles to Supabase
"""

import hashlib
import os
import re
import time
from datetime import datetime, timezone
from html import unescape
from typing import Dict, List

import feedparser
import httpx
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
RSSHUB_BASE = (os.environ.get("RSSHUB_BASE") or "https://rsshub.app").rstrip("/")


def env_float(name: str, default: float) -> float:
    value = (os.environ.get(name) or "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    value = (os.environ.get(name) or "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


REQUEST_TIMEOUT_SECONDS = max(1.0, env_float("FETCH_TIMEOUT_SECONDS", 15.0))
MAX_RETRIES = max(1, env_int("FETCH_RETRIES", 3))
RETRY_BACKOFF_SECONDS = max(0.1, env_float("FETCH_BACKOFF_SECONDS", 1.2))
PER_FEED_LIMIT = max(1, env_int("PER_FEED_LIMIT", 20))

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

FEEDS: List[Dict[str, str]] = [
    # Global official sources
    {"url": "https://openai.com/blog/rss.xml", "source": "OpenAI", "lang": "en"},
    {"url": "https://www.anthropic.com/rss.xml", "source": "Anthropic", "lang": "en"},
    {"url": "https://deepmind.google/blog/rss.xml", "source": "DeepMind", "lang": "en"},
    {"url": "https://ai.meta.com/blog/rss", "source": "Meta AI", "lang": "en"},
    {"url": "https://mistral.ai/news/rss.xml", "source": "Mistral", "lang": "en"},
    # Global media
    {"url": "https://venturebeat.com/category/ai/feed/", "source": "VentureBeat", "lang": "en"},
    {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "source": "TechCrunch", "lang": "en"},
    {"url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "source": "The Verge", "lang": "en"},
    {"url": "https://news.ycombinator.com/rss", "source": "Hacker News", "lang": "en"},
    # Academic
    {"url": "https://arxiv.org/rss/cs.AI", "source": "arXiv cs.AI", "lang": "en"},
    {"url": "https://arxiv.org/rss/cs.LG", "source": "arXiv cs.LG", "lang": "en"},
    # CN via RSSHub
    {"url": f"{RSSHUB_BASE}/jiqizhixin/articles", "source": "机器之心", "lang": "zh"},
    {"url": f"{RSSHUB_BASE}/qbitai", "source": "量子位", "lang": "zh"},
    {"url": f"{RSSHUB_BASE}/zhidongxi/article", "source": "智东西", "lang": "zh"},
    {"url": "https://36kr.com/feed", "source": "36氪", "lang": "zh"},
    # CN direct RSS
    {"url": "https://www.jiqizhixin.com/rss", "source": "机器之心(直连)", "lang": "zh"},
]

CATEGORY_KEYWORDS = {
    "模型发布": ["release", "launch", "model", "gpt", "claude", "gemini", "发布", "上线", "模型"],
    "AI产品": ["product", "app", "feature", "tool", "产品", "功能", "应用", "工具"],
    "研究论文": ["paper", "research", "arxiv", "study", "论文", "研究", "实验"],
    "行业动态": ["funding", "investment", "acquisition", "融资", "收购", "投资", "估值"],
    "政策监管": ["regulation", "policy", "law", "ban", "监管", "政策", "法规", "禁令"],
    "开源项目": ["open source", "github", "open-source", "开源", "代码"],
}


def md5_text(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    if not text:
        return ""
    value = unescape(text)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def url_hash(url: str) -> str:
    return md5_text(url)


def content_hash(title: str, summary: str) -> str:
    # Normalize content to detect same article mirrored on different URLs.
    payload = f"{normalize_text(title).lower()}||{normalize_text(summary).lower()}"
    return md5_text(payload)


def guess_category(title: str, summary: str = "") -> str:
    text = f"{title} {summary}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "其他"


def parse_date(entry) -> str:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


def parse_feed_with_retry(client: httpx.Client, url: str):
    last_error = None
    headers = {"User-Agent": "Mozilla/5.0 AI-News-Fetcher/1.0"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", []):
                raise ValueError(str(getattr(parsed, "bozo_exception", "invalid feed")))
            return parsed
        except Exception as err:
            last_error = err
            if attempt < MAX_RETRIES:
                sleep_for = RETRY_BACKOFF_SECONDS * attempt
                time.sleep(sleep_for)
            continue

    raise RuntimeError(f"fetch failed after {MAX_RETRIES} retries: {last_error}")


def insert_article(row: dict) -> bool:
    """
    Returns True if row inserted, False if skipped by conflict.
    Requires database unique keys on url_hash and content_hash.
    """
    resp = (
        supabase.table("articles")
        .upsert(row, on_conflict="url_hash,content_hash", ignore_duplicates=True)
        .execute()
    )
    return bool(resp.data)


def fetch_and_store():
    stats = {
        "feeds_total": len(FEEDS),
        "feeds_ok": 0,
        "feeds_failed": 0,
        "entries_seen": 0,
        "inserted": 0,
        "deduped": 0,
        "insert_errors": 0,
    }
    started_at = time.time()

    with httpx.Client(follow_redirects=True) as client:
        for feed_cfg in FEEDS:
            print(f"\nFetching: {feed_cfg['source']} ({feed_cfg['url']})")
            try:
                feed = parse_feed_with_retry(client, feed_cfg["url"])
                stats["feeds_ok"] += 1
            except Exception as err:
                stats["feeds_failed"] += 1
                print(f"  x Feed error: {err}")
                continue

            entries = (feed.entries or [])[:PER_FEED_LIMIT]
            for entry in entries:
                stats["entries_seen"] += 1

                url = getattr(entry, "link", "") or ""
                if not url:
                    stats["deduped"] += 1
                    continue

                title = normalize_text(getattr(entry, "title", "") or "")
                summary_raw = normalize_text(getattr(entry, "summary", "") or "")[:1200]
                row = {
                    "url_hash": url_hash(url),
                    "content_hash": content_hash(title, summary_raw),
                    "url": url,
                    "title": title,
                    "summary_raw": summary_raw,
                    "source": feed_cfg["source"],
                    "lang": feed_cfg["lang"],
                    "category": guess_category(title, summary_raw),
                    "status": "pending",  # pending | processed | skipped
                    "published_at": parse_date(entry),
                }

                try:
                    inserted = insert_article(row)
                    if inserted:
                        stats["inserted"] += 1
                        print(f"  + {title[:80]}")
                    else:
                        stats["deduped"] += 1
                except Exception as err:
                    stats["insert_errors"] += 1
                    print(f"  x Insert error: {err}")

    elapsed = round(time.time() - started_at, 2)
    print("\n=== Fetch Summary ===")
    print(f"Feeds:       {stats['feeds_ok']}/{stats['feeds_total']} ok, {stats['feeds_failed']} failed")
    print(f"Entries:     {stats['entries_seen']} seen")
    print(f"Inserted:    {stats['inserted']}")
    print(f"Deduped:     {stats['deduped']}")
    print(f"Insert errs: {stats['insert_errors']}")
    print(f"Elapsed:     {elapsed}s")


if __name__ == "__main__":
    fetch_and_store()
