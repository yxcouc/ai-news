const express = require("express");
const path = require("path");
const RSSParser = require("rss-parser");

const app = express();
const parser = new RSSParser({ timeout: 10000 });

const PORT = process.env.PORT || 5173;
const RSSHUB_BASE = process.env.RSSHUB_BASE || "https://rsshub.app";
const X_TWITTER_USERS = (process.env.X_TWITTER_USERS ||
  "OpenAI,AnthropicAI,GoogleDeepMind,StanfordAILab,GitHub,vercel")
  .split(",")
  .map((item) => item.trim())
  .filter(Boolean);

const baseSources = [
  {
    id: "hn",
    name: "Hacker News",
    group: "Hacker News",
    region: "global",
    url: "https://hnrss.org/frontpage?points=80&count=30",
    tag: "技术",
  },
  {
    id: "ph",
    name: "Product Hunt",
    group: "Product Hunt",
    region: "global",
    url: "https://www.producthunt.com/feed",
    tag: "新品",
  },
  {
    id: "gh",
    name: "GitHub Trending",
    group: "GitHub Trending",
    region: "global",
    url: `${RSSHUB_BASE}/github/trending/daily/any`,
    tag: "开源",
  },
  {
    id: "reddit",
    name: "Reddit r/MachineLearning",
    group: "Reddit",
    region: "global",
    url: "https://www.reddit.com/r/MachineLearning/.rss",
    tag: "社区",
  },
  {
    id: "zhihu",
    name: "知乎热榜",
    group: "知乎热榜",
    region: "cn",
    url: `${RSSHUB_BASE}/zhihu/hotlist`,
    tag: "热榜",
  },
  {
    id: "36kr",
    name: "36Kr",
    group: "36Kr",
    region: "cn",
    url: `${RSSHUB_BASE}/36kr/hot-list/24`,
    tag: "商业",
  },
  {
    id: "sspai",
    name: "少数派",
    group: "少数派",
    region: "cn",
    url: `${RSSHUB_BASE}/sspai/index`,
    tag: "效率",
  },
  {
    id: "qbitai",
    name: "量子位",
    group: "量子位",
    region: "cn",
    url: `${RSSHUB_BASE}/qbitai/category/资讯`,
    tag: "资讯",
  },
  {
    id: "jiqizhixin",
    name: "机器之心",
    group: "机器之心",
    region: "cn",
    url: `${RSSHUB_BASE}/wechat/wasi/5b575dd058e5c4583338dbd3`,
    tag: "媒体",
  },
];

const xSources = X_TWITTER_USERS.map((user) => ({
  id: `x-${user}`,
  name: `X · @${user}`,
  group: "X 热点",
  region: "x",
  url: `${RSSHUB_BASE}/twitter/user/${user}/exclude_replies`,
  altUrl: `https://nitter.net/${user}/rss`,
  tag: "X",
}));

const sources = [...baseSources, ...xSources];

const stripHtml = (value) =>
  (value || "")
    .replace(/<[^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

const hasChinese = (text) => /[\u4e00-\u9fff]/.test(text || "");

const cleanSummary = (summary) =>
  (summary || "")
    .replace(/Article URL:\s*\S+/gi, "")
    .replace(/Comments URL:\s*\S+/gi, "")
    .replace(/Discussion\s*\|\s*Link/gi, "")
    .replace(/\bhttps?:\/\/\S+/gi, "")
    .replace(/\s+/g, " ")
    .trim();

const inferVerb = (title) => {
  const lower = (title || "").toLowerCase();
  if (lower.includes("show hn")) return "展示项目";
  if (lower.includes("open source") || lower.includes("open-source")) return "开源";
  if (lower.includes("release") || lower.includes("released")) return "发布";
  if (lower.includes("launch") || lower.includes("launched")) return "推出";
  if (lower.includes("announce") || lower.includes("announces")) return "宣布";
  if (lower.includes("beta")) return "发布测试版";
  if (lower.includes("update") || lower.includes("adds") || lower.includes("support")) return "更新";
  if (lower.includes("paper")) return "发布论文";
  if (lower.includes("dataset")) return "发布数据集";
  if (lower.includes("benchmark")) return "更新评测";
  if (lower.includes("funding") || lower.includes("raise") || lower.includes("seed")) return "融资";
  if (lower.startsWith("why") || lower.startsWith("how") || lower.startsWith("what")) return "解析";
  return "发布";
};

const clampText = (text, max) => {
  const value = text || "";
  return value.length > max ? `${value.slice(0, max)}…` : value;
};

const normalizeEnglishTitle = (title) =>
  (title || "")
    .replace(/^Show HN:\s*/i, "")
    .replace(/\s*\|\s*.*$/, "")
    .trim();

const buildCnTitle = (title, summary, source) => {
  if (hasChinese(title)) return title;
  const verb = inferVerb(title);
  const core = normalizeEnglishTitle(title) || cleanSummary(summary);
  const composed = `【${source}】${verb}${core}`;
  return clampText(composed, 32);
};

const buildCnSubtitle = (summary, title) => {
  const cleaned = cleanSummary(summary);
  if (hasChinese(cleaned)) return clampText(cleaned, 80);
  const fallback = cleaned || title || "暂无摘要";
  return clampText(`主要信息：${fallback}`, 80);
};

const normalizeItem = (item, source) => {
  const summary = stripHtml(
    item.contentSnippet || item.content || item.summary || item.description
  );

  const cnTitle = buildCnTitle(item.title, summary, source.name);
  const cnSubtitle = buildCnSubtitle(summary, item.title);

  return {
    id: `${source.id}-${item.guid || item.link || item.title}`,
    title: item.title || "未命名",
    summary: summary || "暂无摘要",
    cnTitle,
    cnSubtitle,
    link: item.link,
    pubDate: item.pubDate || item.isoDate,
    source: source.name,
    sourceGroup: source.group,
    region: source.region,
    tags: [source.tag, ...(item.categories || [])].filter(Boolean).slice(0, 3),
  };
};

const fetchFeed = async (source) => {
  try {
    const feed = await parser.parseURL(source.url);
    return feed.items.map((item) => normalizeItem(item, source));
  } catch (err) {
    if (!source.altUrl) return [];
    try {
      const feed = await parser.parseURL(source.altUrl);
      return feed.items.map((item) => normalizeItem(item, source));
    } catch (altErr) {
      return [];
    }
  }
};

const cache = {
  ts: 0,
  items: [],
};

const loadAllFeeds = async () => {
  const now = Date.now();
  if (now - cache.ts < 5 * 60 * 1000 && cache.items.length) {
    return cache.items;
  }

  const results = await Promise.all(sources.map(fetchFeed));
  const items = results.flat().filter((item) => item.title && item.link);

  cache.ts = now;
  cache.items = items;

  return items;
};

app.get("/api/hotlist", async (req, res) => {
  const scope = req.query.scope || "all";
  const limit = Number(req.query.limit || 60);

  const items = await loadAllFeeds();
  const filtered = items.filter((item) => {
    if (scope === "all") return true;
    return scope === item.region;
  });

  res.json({
    updatedAt: new Date().toISOString(),
    total: filtered.length,
    items: filtered.slice(0, limit),
  });
});

app.use(express.static(path.join(__dirname, "..")));

app.listen(PORT, () => {
  console.log(`AI Hot server running at http://localhost:${PORT}`);
});


