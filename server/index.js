const express = require("express");
const path = require("path");
const { createClient } = require("@supabase/supabase-js");

const app = express();
const PORT = Number(process.env.PORT || 5173);

const SUPABASE_URL = process.env.SUPABASE_URL;
const SUPABASE_KEY = process.env.SUPABASE_KEY;

const hasChinese = (text) => /[\u4e00-\u9fff]/.test(text || "");
const clampText = (text, max) => {
  const value = text || "";
  return value.length > max ? `${value.slice(0, max)}…` : value;
};

const normalizeSummary = (value) =>
  (value || "")
    .replace(/<[^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

const makeZhTitleFromSummary = (summary, source) => {
  const text = normalizeSummary(summary);
  if (!text) return "";
  const firstSentence =
    text.split(/(?<=[。！？!?])/)[0] ||
    text.split(/[。！？!?，,]/)[0] ||
    text;
  const core = firstSentence.trim();
  return core ? `【${source}】${core}` : "";
};

const inferRegion = (row) => {
  if ((row.source || "").toLowerCase().includes("x")) return "x";
  if (row.lang === "zh") return "cn";
  return "global";
};

const toHotItem = (row) => {
  const title = (row.title || "未命名").trim();
  const summary = normalizeSummary(row.summary_zh || row.summary_raw || "暂无摘要");
  const source = row.source || "Unknown";
  const region = inferRegion(row);
  const sourceGroup = source;
  const category = row.category || "其他";
  const cnTitle = hasChinese(title)
    ? title
    : makeZhTitleFromSummary(row.summary_zh, source) || `【${source}】${title}`;
  const cnSubtitle = hasChinese(summary)
    ? clampText(summary, 80)
    : clampText(`主要信息：${summary || title}`, 80);

  return {
    id: row.id || row.url_hash || row.url,
    title,
    summary: summary || "暂无摘要",
    cnTitle,
    cnSubtitle,
    link: row.url || "#",
    pubDate: row.published_at || row.created_at,
    source,
    sourceGroup,
    region,
    tags: [category, row.lang || "unknown", source].filter(Boolean).slice(0, 3),
  };
};

const cache = { ts: 0, items: [] };
const CACHE_MS = 60 * 1000;

const ensureSupabase = () => {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    throw new Error("SUPABASE_URL/SUPABASE_KEY 未配置");
  }
  return createClient(SUPABASE_URL, SUPABASE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
};

const loadArticles = async (maxRows = 300) => {
  const now = Date.now();
  if (now - cache.ts < CACHE_MS && cache.items.length) return cache.items;

  const supabase = ensureSupabase();
  const { data, error } = await supabase
    .from("articles")
    .select(
      "id,url,url_hash,title,summary_raw,summary_zh,category,source,lang,published_at,created_at,importance"
    )
    .order("published_at", { ascending: false, nullsFirst: false })
    .order("created_at", { ascending: false, nullsFirst: false })
    .order("importance", { ascending: false, nullsFirst: false })
    .limit(maxRows);

  if (error) throw error;

  const items = (data || []).map(toHotItem);
  cache.ts = now;
  cache.items = items;
  return items;
};

app.get("/api/hotlist", async (req, res) => {
  const scope = String(req.query.scope || "all");
  const limit = Math.max(1, Math.min(Number(req.query.limit || 60), 200));

  try {
    const items = await loadArticles(500);
    const filtered = items.filter((item) => (scope === "all" ? true : item.region === scope));
    res.json({
      updatedAt: new Date().toISOString(),
      total: filtered.length,
      items: filtered.slice(0, limit),
    });
  } catch (err) {
    res.status(500).json({
      updatedAt: new Date().toISOString(),
      total: 0,
      items: [],
      error: err.message || "hotlist query failed",
    });
  }
});

app.use(express.static(path.join(__dirname, "..")));

app.listen(PORT, () => {
  console.log(`AI Hot server running at http://localhost:${PORT}`);
});


