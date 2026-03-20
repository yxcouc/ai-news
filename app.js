const DEFAULT_DATA = [
  {
    date: "3月15日",
    time: "19:51",
    source: "NVIDIA AI Blog",
    tag: "精选",
    title: "全新 NVIDIA Nemotron 3 Super 为智能体 AI 提供 5 倍吞吐量",
    summary:
      "NVIDIA 今日发布 Nemotron 3 Super，这是一个拥有 1200 亿参数、120 亿可训练参数的开源模型。该模型专为大规模运行复杂的智能体 AI 系统设计，核心突破在于吞吐量相较前代实现 5 倍提升，并支持更复杂、更庞大的多智能体系统部署。",
    pills: ["Agent", "模型发布", "部署/工程"],
    score: 82,
    featured: true,
  },
];

const feedView = document.getElementById("feedView");
const strategyView = document.getElementById("strategyView");
const searchInput = document.getElementById("searchInput");
const btnFeatured = document.getElementById("btnFeatured");
const btnAll = document.getElementById("btnAll");
const btnX = document.getElementById("btnX");
const updateTime = document.getElementById("updateTime");
const statTotal = document.getElementById("statTotal");
const statLike = document.getElementById("statLike");
const statDislike = document.getElementById("statDislike");
const statKeys = document.getElementById("statKeys");
const iterateBtn = document.getElementById("iterateBtn");
const resetBtn = document.getElementById("resetBtn");
const menuItems = Array.from(document.querySelectorAll(".menu-item"));

const state = {
  query: "",
  featuredOnly: true,
  scope: "all",
  items: [],
};

const sourceWeights = {
  "Hacker News": 72,
  "Product Hunt": 68,
  "GitHub Trending": 64,
  "Reddit": 60,
  "知乎热榜": 62,
  "36Kr": 66,
  "少数派": 60,
  "机器之心": 70,
  "量子位": 68,
  "X 热点": 62,
};

const skillKeywords = [
  "智能体",
  "多智能体",
  "Agent",
  "模型发布",
  "开源",
  "工具链",
  "推理",
  "多模态",
  "部署",
  "安全",
  "对齐",
  "数据集",
  "评测",
  "MCP",
  "编程",
  "应用",
  "产品",
];

const storageKey = "aihot-feedback-profile";

const loadProfile = () => {
  const raw = localStorage.getItem(storageKey);
  if (!raw) {
    return { likes: 0, dislikes: 0, keywordWeights: {}, votes: {} };
  }
  try {
    return JSON.parse(raw);
  } catch (err) {
    return { likes: 0, dislikes: 0, keywordWeights: {}, votes: {} };
  }
};

const saveProfile = (profile) => {
  localStorage.setItem(storageKey, JSON.stringify(profile));
};

let profile = loadProfile();

const normalizeText = (text) => (text || "").toLowerCase();
const hasChinese = (text) => /[\u4e00-\u9fff]/.test(text || "");
const clampText = (text, max) =>
  (text || "").length > max ? `${(text || "").slice(0, max)}…` : text || "";

const makeCnTitle = (item) => {
  if (item.cnTitle) return item.cnTitle;
  if (hasChinese(item.title)) return item.title;
  if (hasChinese(item.summary)) return clampText(item.summary, 24);
  return clampText(item.title, 24);
};

const makeCnSubtitle = (item) => {
  if (item.cnSubtitle) return item.cnSubtitle;
  if (hasChinese(item.summary)) return item.summary || "";
  return item.summary ? `主要信息：${item.summary}` : item.title || "";
};

const extractKeywords = (text) => {
  const lower = normalizeText(text);
  return skillKeywords.filter((key) => lower.includes(key.toLowerCase()));
};

const computeScore = (item) => {
  const base = sourceWeights[item.sourceGroup] || 60;
  const keywords = extractKeywords(`${item.title} ${item.summary}`);
  const keywordBoost = keywords.reduce((sum, key) => {
    return sum + (profile.keywordWeights[key] || 0);
  }, 0);

  const recencyBoost = item.pubDate
    ? Math.max(0, 10 - item.hoursAgo * 0.4)
    : 0;

  return Math.round(base + keywordBoost + recencyBoost);
};

const updateProfileStats = () => {
  statTotal.textContent = profile.likes + profile.dislikes;
  statLike.textContent = profile.likes;
  statDislike.textContent = profile.dislikes;

  const topKeys = Object.entries(profile.keywordWeights)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([key, value]) => `${key} +${value.toFixed(1)}`)
    .join(" · ");

  statKeys.textContent = topKeys || "—";
};

const itemKeywordIndex = {};

const rebuildKeywordWeights = () => {
  const weights = {};
  let likes = 0;
  let dislikes = 0;

  Object.entries(profile.votes).forEach(([id, vote]) => {
    const delta = vote === "up" ? 1.2 : -1;
    if (vote === "up") likes += 1;
    if (vote === "down") dislikes += 1;

    (itemKeywordIndex[id] || []).forEach((key) => {
      weights[key] = (weights[key] || 0) + delta;
    });
  });

  profile.keywordWeights = weights;
  profile.likes = likes;
  profile.dislikes = dislikes;
};

const toggleVote = (itemId, vote) => {
  const prev = profile.votes[itemId];

  if (prev === vote) {
    delete profile.votes[itemId];
  } else {
    profile.votes[itemId] = vote;
  }

  rebuildKeywordWeights();

  saveProfile(profile);
  updateProfileStats();
  rebuildScores();
  render();
};

const rebuildScores = () => {
  state.items = state.items.map((item) => {
    const score = computeScore(item);
    const skillBoost = extractKeywords(`${item.title} ${item.summary}`).reduce(
      (sum, key) => sum + (profile.keywordWeights[key] || 0),
      0
    );
    return { ...item, score, skillBoost };
  });

  const scores = state.items.map((item) => item.score).sort((a, b) => b - a);
  const threshold = scores.length
    ? scores[Math.floor(scores.length * 0.4)]
    : 0;

  state.items = state.items.map((item) => ({
    ...item,
    featured: item.score >= threshold,
  }));
};

const formatGroups = (items) => {
  const groups = {};
  items.forEach((item) => {
    if (!groups[item.date]) {
      groups[item.date] = [];
    }
    groups[item.date].push(item);
  });
  return Object.entries(groups);
};

const render = () => {
  const filtered = state.items
    .filter((item) => {
      const q = state.query.trim().toLowerCase();
      const matchesQuery =
        !q ||
        item.title.toLowerCase().includes(q) ||
        item.summary.toLowerCase().includes(q);
      const matchesFeatured = !state.featuredOnly || item.featured;
      return matchesQuery && matchesFeatured;
    })
    .sort((a, b) => {
      const ta = a.pubDate ? new Date(a.pubDate).getTime() : 0;
      const tb = b.pubDate ? new Date(b.pubDate).getTime() : 0;
      // Latest first, keep score as secondary sort.
      if (tb !== ta) return tb - ta;
      return (b.score || 0) - (a.score || 0);
    });

  feedView.innerHTML = "";
  formatGroups(filtered).forEach(([date, items]) => {
    const group = document.createElement("div");
    group.className = "day-group";

    group.innerHTML = `
      <div class="day-label">
        <div class="date">${date}</div>
        <div>${items.length} 条</div>
      </div>
      <div class="timeline"></div>
    `;

    const timeline = group.querySelector(".timeline");
    items.forEach((item) => {
      const card = document.createElement("article");
      card.className = "card";

      const vote = profile.votes[item.id];
      card.innerHTML = `
        <div class="card-header">
          <div class="badge">
            <span>${item.time}</span>
            <span>·</span>
            <span>${item.source}</span>
            <span class="tag">${item.tag}</span>
          </div>
          <div class="score">${item.score}</div>
        </div>
        <h3><a href="${item.link || "#"}" target="_blank" rel="noopener">${item.cnTitle}</a></h3>
        <p>${item.cnSubtitle}</p>
        <div class="card-footer">
          ${item.pills.map((pill) => `<span class="pill">${pill}</span>`).join("")}
        </div>
        <div class="card-actions">
          <button class="action-btn ${vote === "up" ? "active" : ""}" data-id="${item.id}" data-vote="up">赞同</button>
          <button class="action-btn ${vote === "down" ? "active" : ""}" data-id="${item.id}" data-vote="down">反对</button>
          <div class="score-detail">技能偏好 +${item.skillBoost.toFixed(1)}</div>
        </div>
      `;
      timeline.appendChild(card);
    });

    feedView.appendChild(group);
  });

  if (!filtered.length) {
    feedView.innerHTML = '<div class="card">没有匹配的热点内容。</div>';
  }

  document.querySelectorAll(".action-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      const vote = btn.dataset.vote;
      toggleVote(id, vote);
    });
  });
};

const updateClock = () => {
  const now = new Date();
  updateTime.textContent = now.toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const hydrateItems = (items) => {
  const now = Date.now();
  state.items = items.map((item, index) => {
    const pub = item.pubDate ? new Date(item.pubDate).getTime() : now;
    const hoursAgo = Math.max(0, (now - pub) / 36e5);
    const date = new Date(pub).toLocaleDateString("zh-CN", {
      month: "numeric",
      day: "numeric",
    });
    const time = new Date(pub).toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });

    const pills = item.tags?.length
      ? item.tags.slice(0, 3)
      : [item.region, "热点", item.sourceGroup].filter(Boolean);

    const mapped = {
      id: item.id || `${item.sourceGroup}-${index}`,
      date: `${date.replace("/", "月")}日`,
      time,
      source: item.source,
      sourceGroup: item.sourceGroup,
      tag: item.featuredTag || "精选",
      title: item.title,
      summary: item.summary || "暂无摘要",
      cnTitle: makeCnTitle(item),
      cnSubtitle: makeCnSubtitle(item),
      pills,
      link: item.link,
      pubDate: item.pubDate,
      hoursAgo,
    };

    itemKeywordIndex[mapped.id] = extractKeywords(`${mapped.title} ${mapped.summary}`);

    return mapped;
  });

  rebuildKeywordWeights();
  rebuildScores();
};

const loadHotlist = async () => {
  try {
    const resp = await fetch(`/api/hotlist?scope=${state.scope}&limit=60`);
    if (!resp.ok) throw new Error("hotlist fetch failed");
    const data = await resp.json();
    hydrateItems(data.items || []);
  } catch (err) {
    hydrateItems(
      DEFAULT_DATA.map((item) => ({
        ...item,
        id: `${item.source}-${item.time}`,
        sourceGroup: item.source,
        tags: item.pills,
        summary: item.summary,
        title: item.title,
        region: "fallback",
        link: "#",
        pubDate: new Date().toISOString(),
      }))
    );
  }

  render();
};

const setActiveMenu = (label) => {
  menuItems.forEach((item) => {
    item.classList.toggle("active", item.textContent.trim() === label);
  });

  const isStrategy = label === "策略迭代";
  strategyView.classList.toggle("is-hidden", !isStrategy);
  feedView.classList.toggle("is-hidden", isStrategy);

  if (label === "X监控") {
    state.scope = "x";
    btnX.classList.add("active");
    loadHotlist();
  } else if (label === "热点资讯") {
    state.scope = "all";
    btnX.classList.remove("active");
    loadHotlist();
  }
};

searchInput.addEventListener("input", (event) => {
  state.query = event.target.value;
  render();
});

btnFeatured.addEventListener("click", () => {
  state.featuredOnly = true;
  btnFeatured.classList.add("active");
  btnAll.classList.remove("active");
  render();
});

btnAll.addEventListener("click", () => {
  state.featuredOnly = false;
  btnAll.classList.add("active");
  btnFeatured.classList.remove("active");
  render();
});

btnX.addEventListener("click", () => {
  state.scope = state.scope === "x" ? "all" : "x";
  btnX.classList.toggle("active", state.scope === "x");
  loadHotlist();
});

iterateBtn.addEventListener("click", () => {
  rebuildScores();
  render();
});

resetBtn.addEventListener("click", () => {
  profile = { likes: 0, dislikes: 0, keywordWeights: {}, votes: {} };
  saveProfile(profile);
  updateProfileStats();
  rebuildScores();
  render();
});

menuItems.forEach((item) => {
  item.addEventListener("click", () => {
    setActiveMenu(item.textContent.trim());
  });
});

updateClock();
setInterval(updateClock, 60000);
rebuildKeywordWeights();
updateProfileStats();
loadHotlist();
setActiveMenu("热点资讯");






