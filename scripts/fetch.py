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
AI_BASE_URL = (os.environ.get("AI_BASE_URL") or "https://coding.dashscope.aliyuncs.com/v1").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL") or "qwen3.5-plus"
AI_FALLBACK_MODEL = os.environ.get("AI_FALLBACK_MODEL") or "qwen3-coder-plus"
AI_API_KEY = os.environ.get("AI_API_KEY") or ""
AI_TIMEOUT_SECONDS = max(5.0, env_float("AI_TIMEOUT_SECONDS", 30.0))
AI_MAX_ITEMS_PER_RUN = max(0, env_int("AI_MAX_ITEMS_PER_RUN", 30))
AI_RETRIES = max(1, env_int("AI_RETRIES", 2))
AI_RETRY_BACKOFF_SECONDS = max(0.2, env_float("AI_RETRY_BACKOFF_SECONDS", 1.5))
AI_INPUT_CHARS = max(200, env_int("AI_INPUT_CHARS", 700))

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

FEEDS: List[Dict[str, str]] = [
    # ── 海外 AI 厂商官方 ───────────────────────────────────────
    {"url": "https://openai.com/blog/rss.xml",              "source": "OpenAI",        "lang": "en"},
    {"url": "https://www.anthropic.com/rss.xml",            "source": "Anthropic",     "lang": "en"},
    {"url": "https://deepmind.google/blog/rss.xml",         "source": "DeepMind",      "lang": "en"},
    {"url": "https://ai.meta.com/blog/rss",                 "source": "Meta AI",       "lang": "en"},
    {"url": "https://mistral.ai/news/rss.xml",              "source": "Mistral",       "lang": "en"},
    {"url": "https://huggingface.co/blog/feed.xml",         "source": "HuggingFace",   "lang": "en"},
    {"url": "https://blog.research.google/feeds/posts/default", "source": "Google AI Blog", "lang": "en"},
    # ── 海外科技媒体 ────────────────────────────────────────────
    {"url": "https://venturebeat.com/category/ai/feed/",   "source": "VentureBeat",   "lang": "en"},
    {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "source": "TechCrunch", "lang": "en"},
    {"url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "source": "The Verge", "lang": "en"},
    {"url": "https://www.wired.com/feed/tag/artificial-intelligence/latest/rss", "source": "Wired AI", "lang": "en"},
    {"url": "https://www.technologyreview.com/feed/",       "source": "MIT Tech Review","lang": "en"},
    {"url": "https://news.ycombinator.com/rss",             "source": "Hacker News",   "lang": "en"},
    # ── 学术 ──────────────────────────────────────────────────
    {"url": "https://arxiv.org/rss/cs.AI",  "source": "arXiv cs.AI",  "lang": "en"},
    {"url": "https://arxiv.org/rss/cs.LG",  "source": "arXiv cs.LG",  "lang": "en"},
    {"url": "https://arxiv.org/rss/cs.CL",  "source": "arXiv cs.CL",  "lang": "en"},
    # ── 国内媒体 (直接 RSS) ────────────────────────────────────
    {"url": "https://36kr.com/feed",                        "source": "36氪",          "lang": "zh"},
    {"url": "https://sspai.com/feed",                       "source": "少数派",         "lang": "zh"},
    {"url": "https://www.infoq.cn/feed",                    "source": "InfoQ China",   "lang": "zh"},
    {"url": "https://readhub.cn/rss",                       "source": "Readhub",       "lang": "zh"},
    {"url": "https://aiera.com.cn/feed",                    "source": "新智元",         "lang": "zh"},
    # ── 国内媒体 (via RSSHub，需配置 RSSHUB_BASE) ───────────────
    {"url": f"{RSSHUB_BASE}/jiqizhixin/articles",           "source": "机器之心",       "lang": "zh"},
    {"url": f"{RSSHUB_BASE}/qbitai",                        "source": "量子位",         "lang": "zh"},
    {"url": f"{RSSHUB_BASE}/zhidongxi/article",             "source": "智东西",         "lang": "zh"},
    {"url": f"{RSSHUB_BASE}/sspai/matrix",                  "source": "少数派Matrix",   "lang": "zh"},
    # ── 微信公众号 (via decemberpei.cyou/rssbox) ─────────────────
    # AI/人工智能
    {"url": "https://decemberpei.cyou/rssbox/wechat-jiqizhixin.xml",          "source": "机器之心(公众号)",     "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-liangziwei.xml",          "source": "量子位(公众号)",       "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-xinzhiyuan.xml",          "source": "新智元(公众号)",       "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-shenkeji.xml",            "source": "DeepTech深科技",      "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-paperweekly.xml",         "source": "PaperWeekly",         "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-aiqianxian.xml",          "source": "AI前线",              "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-xixiaoyaokejishuo.xml",   "source": "夕小瑶科技说",         "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-haiwaidujiaoshou.xml",    "source": "海外独角兽",           "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-jiaziguangnian.xml",      "source": "甲子光年",            "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-jizhijvlebu.xml",         "source": "集智俱乐部",           "lang": "zh"},
    # 科技媒体
    {"url": "https://decemberpei.cyou/rssbox/wechat-jikegongyuan.xml",        "source": "极客公园",            "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-githubdaily.xml",         "source": "GitHubDaily",         "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-wandian.xml",             "source": "晚点LatePost",        "lang": "zh"},
    {"url": "https://decemberpei.cyou/rssbox/wechat-36ke.xml",                "source": "36氪(公众号)",        "lang": "zh"},
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


def summarize_zh_with_ai(client: httpx.Client, title: str, summary_raw: str):
    if not AI_API_KEY:
        return ""

    prompt = (
        "请用中文输出3句话总结这篇AI资讯："
        "第1句说明是什么，第2句说明为什么重要，第3句说明可能影响。"
        "要求简洁、信息密度高，不要使用项目符号，每句不超过40字。\n\n"
        f"标题：{title}\n"
        f"正文片段：{summary_raw[:AI_INPUT_CHARS]}"
    )
    last_error = None
    models = [AI_MODEL]
    if AI_FALLBACK_MODEL and AI_FALLBACK_MODEL != AI_MODEL:
        models.append(AI_FALLBACK_MODEL)

    for model_name in models:
        for attempt in range(1, AI_RETRIES + 1):
            try:
                resp = client.post(
                    f"{AI_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {AI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_name,
                        "temperature": 0.1,
                        "max_tokens": 140,
                        "messages": [
                            {"role": "system", "content": "你是中文科技编辑，擅长压缩资讯要点。"},
                            {"role": "user", "content": prompt},
                        ],
                    },
                    timeout=httpx.Timeout(
                        timeout=AI_TIMEOUT_SECONDS,
                        connect=10.0,
                        read=AI_TIMEOUT_SECONDS,
                        write=20.0,
                    ),
                )
                resp.raise_for_status()
                data = resp.json()
                content = ""

                choices = data.get("choices") or []
                if choices:
                    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
                    raw_content = message.get("content", "")
                    if isinstance(raw_content, list):
                        content = " ".join(
                            chunk.get("text", "")
                            for chunk in raw_content
                            if isinstance(chunk, dict)
                        )
                    else:
                        content = str(raw_content or "")

                if not content:
                    content = str(data.get("output_text") or data.get("text") or "")

                normalized = normalize_text(content)
                if not normalized:
                    snippet = str(data)[:400].replace("\n", " ")
                    print(f"  ! AI empty response ({model_name}): {snippet}")
                    return "", False
                return normalized, False
            except Exception as err:
                last_error = err
                if attempt < AI_RETRIES:
                    time.sleep(AI_RETRY_BACKOFF_SECONDS * attempt)
                continue

        print(f"  ! AI model fallback: {model_name} failed, trying next")

    print(f"  x AI call error after retries/models: {last_error}")
    return "", True


def insert_article(row: dict) -> bool:
    """
    Returns True if row inserted, False if skipped by conflict.
    Uses database unique keys on url_hash/content_hash for dedupe.
    """
    try:
        supabase.table("articles").insert(row).execute()
        return True
    except Exception as err:
        text = str(err).lower()
        # Postgres unique violation (23505) -> treat as deduped.
        if "23505" in text or "duplicate key value" in text or "unique constraint" in text:
            return False
        raise


def update_article_summary(url_hash_value: str, summary_zh: str) -> None:
    supabase.table("articles").update(
        {"summary_zh": summary_zh, "status": "processed"}
    ).eq("url_hash", url_hash_value).execute()


def fetch_and_store():
    stats = {
        "feeds_total": len(FEEDS),
        "feeds_ok": 0,
        "feeds_failed": 0,
        "entries_seen": 0,
        "inserted": 0,
        "deduped": 0,
        "insert_errors": 0,
        "ai_attempted": 0,
        "ai_success": 0,
        "ai_errors": 0,
        "ai_empty": 0,
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
                    "summary_zh": "",
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
                        if AI_API_KEY and stats["ai_attempted"] < AI_MAX_ITEMS_PER_RUN:
                            stats["ai_attempted"] += 1
                            summary_zh, ai_failed = summarize_zh_with_ai(client, title, summary_raw)
                            if summary_zh:
                                try:
                                    update_article_summary(row["url_hash"], summary_zh)
                                    stats["ai_success"] += 1
                                except Exception as err:
                                    stats["ai_errors"] += 1
                                    print(f"  x AI update error: {err}")
                            else:
                                if ai_failed:
                                    stats["ai_errors"] += 1
                                else:
                                    stats["ai_empty"] += 1
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
    print(f"AI attempts: {stats['ai_attempted']}")
    print(f"AI success:  {stats['ai_success']}")
    print(f"AI errors:   {stats['ai_errors']}")
    print(f"AI empty:    {stats['ai_empty']}")
    print(f"Elapsed:     {elapsed}s")


if __name__ == "__main__":
    fetch_and_store()
