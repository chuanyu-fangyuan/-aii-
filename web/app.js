/* AI 情报站 - 前端主逻辑
 * 数据来自 fetch.py 生成的 data.json；所有外部内容均以 textContent 渲染，防 XSS。
 * 时间口径：存储为 UTC ISO，展示统一转为 Asia/Shanghai。
 */
(function () {
  "use strict";

  var TZ = "Asia/Shanghai";
  // API 基地址：本地开发用 localhost，线上部署时改为 Fly.io 域名
  var API_BASE = window.AI_API_BASE || "";
  var state = {
    view: "feed",          // feed | graph
    range: "today",        // today | week | all
    query: "",
    source: null,          // null = 全部来源
    category: null,        // null = 全部分类
    data: null,
    dataSource: "static",  // static | api
    kwByNewsId: {},        // news_id -> [keyword label]
    newsById: {},          // id -> news item
    nodeById: null,        // graph node id -> node（一次建索引，替代反复 find）
  };

  /* ---------- AI 分类配色（7 色 + 其他） ---------- */
  var CATEGORY_COLORS = {
    "模型":     "#007AFF",
    "应用":     "#34C759",
    "芯片硬件": "#FF9500",
    "开源":     "#AF52DE",
    "融资创业": "#FF3B30",
    "政策监管": "#5856D6",
    "研究突破": "#00C7BE",
    "其他":     "#8E8E93",
  };
  var VALID_CATEGORIES = Object.keys(CATEGORY_COLORS);

  /* ---------- DOM 工具 ---------- */
  function h(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  }
  function $(id) { return document.getElementById(id); }

  /* ---------- 时间 ---------- */
  function effectiveTime(item) {
    return item.published_at || item.fetched_at;
  }
  function shanghaiParts(iso) {
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
    }).format(new Date(iso));
  }
  function formatTime(iso, withTime) {
    var opt = { timeZone: TZ, month: "2-digit", day: "2-digit" };
    if (withTime) { opt.hour = "2-digit"; opt.minute = "2-digit"; opt.hour12 = false; }
    return new Intl.DateTimeFormat("zh-CN", opt).format(new Date(iso));
  }
  function isToday(item) {
    return shanghaiParts(effectiveTime(item)) === shanghaiParts(new Date().toISOString());
  }
  function withinWeek(item) {
    return Date.now() - new Date(effectiveTime(item)).getTime() <= 7 * 864e5;
  }

  /* ---------- 过滤 ---------- */
  function filteredNews() {
    var q = state.query.trim().toLowerCase();
    return state.data.news.filter(function (it) {
      if (state.range === "today" && !isToday(it)) return false;
      if (state.range === "week" && !withinWeek(it)) return false;
      if (state.source && it.source_id !== state.source) return false;
      if (state.category && it.ai_category !== state.category) return false;
      if (q) {
        var hay = (it.title + " " + (it.summary || "")).toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });
  }
  function hasActiveFilter() {
    return state.range !== "today" || !!state.query.trim() || !!state.source || !!state.category;
  }

  /* ---------- 渲染：今日速读 ---------- */
  function renderDigest() {
    var box = $("digestCard");
    var d = state.data.digest;
    if (state.range !== "today" || state.query.trim() || state.source || !d || !d.topics.length) {
      box.hidden = true;
      box.textContent = "";
      return;
    }
    box.hidden = false;
    box.textContent = "";

    var head = h("div", "digest-head");
    head.appendChild(h("span", "digest-title", "今日速读"));
    head.appendChild(h("span", "digest-meta",
      d.date + "（北京时间）· 今日收录 " + d.total_today + " 条 · " + d.topics.length + " 个热点话题"));
    box.appendChild(head);

    d.topics.forEach(function (tp) {
      var item = h("div", "digest-topic");
      var line = h("div", "digest-topic-head");
      var kwBtn = h("button", "digest-kw", tp.keyword);
      kwBtn.type = "button";
      kwBtn.title = "在关系图谱中查看";
      kwBtn.addEventListener("click", function () { showKeywordInGraph(tp.keyword); });
      line.appendChild(kwBtn);
      line.appendChild(h("span", "digest-count", tp.count + " 篇相关报道"));
      item.appendChild(line);

      var ul = h("ul", "digest-links");
      tp.news_ids.slice(0, 4).forEach(function (id) {
        var it = state.newsById[id];
        if (!it) return;
        var li = h("li");
        var a = h("a", null, it.title);
        a.href = it.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        li.appendChild(a);
        li.appendChild(h("span", "digest-src", it.source_name));
        ul.appendChild(li);
      });
      item.appendChild(ul);
      box.appendChild(item);
    });

    box.appendChild(h("div", "digest-note", d.note));
  }

  /* ---------- 渲染：资讯流 ---------- */
  function renderFeed() {
    var list = $("feedList");
    list.textContent = "";
    var items = filteredNews();
    $("emptyState").hidden = items.length > 0;
    $("clearBtn").hidden = !hasActiveFilter();

    // 「今天」无内容时的降级：引导看近 7 天（如清晨尚未更新）
    var emptyTitle = $("emptyState").querySelector(".empty-title");
    var emptyDesc = $("emptyState").querySelector(".empty-desc");
    var emptyBtn = $("emptyClearBtn");
    if (!items.length && state.range === "today" && !state.query.trim() && !state.source) {
      var sched = scheduleInfo();
      emptyTitle.textContent = "今天还没有收录新资讯";
      emptyDesc.textContent = "数据" + sched.desc + "（北京时间 " + sched.times + "），可以先看看近 7 天的内容。";
      emptyBtn.textContent = "查看近 7 天";
      emptyBtn.onclick = function () {
        state.range = "week";
        document.querySelectorAll(".date-tab").forEach(function (x) {
          x.classList.toggle("active", x.dataset.range === "week");
        });
        renderAll();
      };
    } else if (!items.length && state.range === "today" && state.source && !state.query.trim()) {
      // 「今天 + 某来源」为空：多半是时区差异（欧美来源今天尚未发稿）
      var srcName = "";
      state.data.meta.sources.forEach(function (s) {
        var n = state.data.news.find(function (x) { return x.source_id === s.source_id; });
        if (s.source_id === state.source) srcName = (n && n.source_name) || s.source_id;
      });
      emptyTitle.textContent = "「" + srcName + "」今天暂无新资讯";
      emptyDesc.textContent = "该来源最近的文章发布于昨天或更早（时区差异），不代表抓取失败。";
      emptyBtn.textContent = "查看该来源近 7 天";
      emptyBtn.onclick = function () {
        state.range = "week";
        document.querySelectorAll(".date-tab").forEach(function (x) {
          x.classList.toggle("active", x.dataset.range === "week");
        });
        renderAll();
      };
    } else {
      emptyTitle.textContent = "没有匹配的资讯";
      emptyDesc.textContent = "试试更换关键词、来源或时间范围。";
      emptyBtn.textContent = "清除全部条件";
      emptyBtn.onclick = clearAllFilters;
    }

    items.forEach(function (it) {
      var card = h("article", "card");

      var title = h("h2", "card-title");
      var a = h("a", null, it.title);
      a.href = it.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      title.appendChild(a);
      card.appendChild(title);

      // AI 分类 chip（有分类才渲染）
      if (it.ai_category && VALID_CATEGORIES.indexOf(it.ai_category) !== -1) {
        var chip = h("span", "ai-chip", it.ai_category);
        chip.style.backgroundColor = CATEGORY_COLORS[it.ai_category] + "18";
        chip.style.color = CATEGORY_COLORS[it.ai_category];
        chip.style.borderColor = CATEGORY_COLORS[it.ai_category] + "40";
        chip.title = (it.ai_summary_zh || "AI 分类");
        chip.style.cursor = "pointer";
        chip.addEventListener("click", function (e) {
          e.stopPropagation();
          state.category = state.category === it.ai_category ? null : it.ai_category;
          renderAll();
        });
        card.appendChild(chip);
      }

      // AI 中文摘要（优先展示，无则用原始 summary）
      var summaryText = it.ai_summary_zh || it.summary || "";
      if (summaryText) card.appendChild(h("p", "card-summary", summaryText));

      // 验证角标（Day 6）
      if (it.verification) {
        var vIcon = it.verification === "confirmed" ? "✅" :
                    it.verification === "disputed" ? "❌" :
                    it.verification === "unverified" ? "⚠️" : "";
        if (vIcon) {
          var vBadge = h("span", "verify-badge", vIcon);
          vBadge.title = it.verification_note || it.verification;
          card.appendChild(vBadge);
        }
      }

      var meta = h("div", "card-meta");
      meta.appendChild(h("span", "meta-source", it.source_name));

      if (it.published_unknown) {
        var t1 = h("span", "meta-time unknown", "发布时间未知 · 采集于 " + formatTime(it.fetched_at, true));
        t1.title = "原始来源未提供发布时间，展示采集时间（不冒充发布时间）";
        meta.appendChild(t1);
      } else {
        meta.appendChild(h("span", "meta-time", formatTime(it.published_at, true)));
      }

      var kws = state.kwByNewsId[it.id] || [];
      if (kws.length) {
        var kwBox = h("span", "meta-kws");
        kws.slice(0, 4).forEach(function (kw) {
          var pill = h("button", "meta-kw", kw);
          pill.type = "button";
          pill.title = "在关系图谱中查看「" + kw + "」";
          pill.addEventListener("click", function () { showKeywordInGraph(kw); });
          kwBox.appendChild(pill);
        });
        meta.appendChild(kwBox);
      }

      card.appendChild(meta);
      list.appendChild(card);
    });
  }

  /* ---------- 渲染：来源筛选 chips / 状态 ---------- */
  var STATUS_LABEL = { ok: "正常", no_new: "无新增", failed: "抓取失败" };
  function statusDot(status) {
    var dot = h("span", "dot");
    dot.classList.add(status === "ok" ? "ok" : status === "no_new" ? "warn" : "fail");
    return dot;
  }

  function renderSourceChips() {
    var box = $("sourceChips");
    box.textContent = "";
    state.data.meta.sources.forEach(function (s) {
      var name = (state.data.news.find(function (n) { return n.source_id === s.source_id; }) || {}).source_name || s.source_id;
      var chip = h("button", "chip" + (state.source === s.source_id ? " active" : ""), name);
      chip.type = "button";
      chip.addEventListener("click", function () {
        state.source = state.source === s.source_id ? null : s.source_id;
        renderAll();
      });
      box.appendChild(chip);
    });
  }

  /* ---------- 更新时效展示 ---------- */
  function relativeTime(iso) {
    var diff = Date.now() - new Date(iso).getTime();
    var m = Math.floor(diff / 6e4);
    if (m < 1) return "刚刚";
    if (m < 60) return m + " 分钟前";
    var hh = Math.floor(m / 60);
    if (hh < 24) return hh + " 小时前";
    return Math.floor(hh / 24) + " 天前";
  }

  /* 更新节奏读自 data.json 的 meta.schedule（由 fetch.py 生成），不在前端硬编码，
   * 否则调整定时策略后页面文案会与事实不符。旧数据缺该字段时回落到通用描述。 */
  function scheduleInfo() {
    var s = (state.data && state.data.meta && state.data.meta.schedule) || {};
    return {
      desc: s.description || "定时自动更新",
      trigger: s.trigger || "由定时任务自动采集更新，无需打开网页、也无需保持电脑开机",
      times: (s.times_local || []).join(" / ") || "定时",
    };
  }

  function renderStatus() {
    var meta = state.data.meta;
    var worst = "ok";
    meta.sources.forEach(function (s) {
      if (s.status === "failed") worst = "fail";
      else if (s.status === "no_new" && worst === "ok") worst = "warn";
    });
    $("updateDot").className = "dot " + worst;
    var sched = scheduleInfo();
    $("updateText").textContent =
      relativeTime(meta.generated_at) + "更新 · " + sched.desc;
    $("updateBadge").title =
      "数据生成于 " + formatTime(meta.generated_at, true) +
      "（Asia/Shanghai）\n" + sched.trigger +
      "\n验证方式：仓库 Actions 页面可查看每次运行记录";

    var box = $("sourceStatus");
    box.textContent = "";
    meta.sources.forEach(function (s) {
      var name = (state.data.news.find(function (n) { return n.source_id === s.source_id; }) || {}).source_name || s.source_id;
      var st = h("span", "src-st");
      st.appendChild(statusDot(s.status));
      var txt = name + " " + STATUS_LABEL[s.status] + " · " + relativeTime(s.run_at);
      if (s.status === "failed" && s.message) txt += "（" + s.message.split(":")[0] + "）";
      st.appendChild(h("span", null, txt));
      box.appendChild(st);
    });

    renderMemoryNote();
  }

  /* 记忆策略说明：把「为什么图谱里的条数比列表少」讲清楚。
   * 数字全部读自 data.json 的 meta.window，改配置后页面文案自动跟着变。 */
  function renderMemoryNote() {
    var box = $("memoryNote");
    var w = (state.data.meta && state.data.meta.window) || null;
    if (!w) { box.hidden = true; return; }
    box.hidden = false;
    var parts = [
      "采集配额：每天最多入库 " + w.daily_ingest_limit + " 条",
      "记忆衰减：半衰期 " + w.graph_half_life_hours + " 小时",
      "图谱容量：" + w.graph_days + " 天内按记忆强度保留 " + w.graph_max_news
        + " 条资讯 + " + w.graph_max_keywords + " 个关键词",
      "归档保留：" + w.db_retention_days + " 天",
    ];
    box.textContent = "数据治理（遗忘策略）— " + parts.join(" · ")
      + "。被遗忘的内容不再进图谱，但仍在资讯流中可读。";
  }

  /* ---------- 抽屉 ---------- */
  function openDrawer(contentNode) {
    var c = $("drawerContent");
    c.textContent = "";
    c.appendChild(contentNode);
    $("drawer").hidden = false;
  }
  function closeDrawer() { $("drawer").hidden = true; }

  function newsDrawer(it) {
    var wrap = h("div");
    wrap.appendChild(h("h2", null, it.title));
    var sub = it.source_name + " · " +
      (it.published_unknown
        ? "发布时间未知 · 采集于 " + formatTime(it.fetched_at, true)
        : formatTime(it.published_at, true));
    wrap.appendChild(h("div", "drawer-sub", sub));
    if (it.summary) wrap.appendChild(h("p", null, it.summary));
    var link = h("a", "ext-link", "阅读原文 →");
    link.href = it.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    wrap.appendChild(link);

    var kws = state.kwByNewsId[it.id] || [];
    if (kws.length) {
      var box = h("div", "drawer-list");
      kws.forEach(function (kw) {
        var pill = h("button", "meta-kw", kw);
        pill.type = "button";
        pill.addEventListener("click", function () { keywordDrawer(kw); });
        box.appendChild(pill);
      });
      wrap.appendChild(h("div", "drawer-sub", "关联关键词"));
      wrap.appendChild(box);
    }
    openDrawer(wrap);
  }

  function keywordDrawer(kw) {
    var wrap = h("div");
    wrap.appendChild(h("span", "drawer-kw-pill", kw));
    wrap.appendChild(h("h2", null, "关键词 · " + kw));
    var related = state.data.news.filter(function (it) {
      return (state.kwByNewsId[it.id] || []).indexOf(kw) !== -1;
    });
    wrap.appendChild(h("div", "drawer-sub", "共 " + related.length + " 条相关资讯"));
    var list = h("div", "drawer-list");
    related.forEach(function (it) {
      var card = h("article", "card");
      var title = h("h2", "card-title");
      var a = h("a", null, it.title);
      a.href = it.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      title.appendChild(a);
      card.appendChild(title);
      card.appendChild(h("div", "card-meta", it.source_name + " · " + formatTime(effectiveTime(it), false)));
      card.style.cursor = "pointer";
      card.addEventListener("click", function (e) {
        if (e.target.tagName !== "A") newsDrawer(it);
      });
      list.appendChild(card);
    });
    wrap.appendChild(list);
    openDrawer(wrap);
  }

  /* ---------- 视图切换 ---------- */
  function switchView(view) {
    state.view = view;
    document.querySelectorAll(".view-tab").forEach(function (t) {
      var active = t.dataset.view === view;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", active);
    });
    $("feedView").hidden = view !== "feed";
    $("graphView").hidden = view !== "graph";
    var askViewEl = $("askView");
    if (askViewEl) askViewEl.hidden = view !== "ask";
    if (view === "graph") {
      renderGraph();
    } else if (window.GraphView.pause) {
      // 离开图谱即暂停仿真：容器已 hidden，继续跑只是白烧 CPU
      window.GraphView.pause();
    }
  }

  /* 图谱子图：当前筛选命中的新闻 + 仍与它们相连的关键词。
   *
   * 旧实现直接沿用全量图谱，只在渲染前把新闻节点换成筛选结果，于是：
   *   ① 关键词节点的 count 是全量口径，与眼前的筛选条件不符（「今天」里挂着 142 篇的 "News"）；
   *   ② 与当前筛选毫无关系的关键词仍以孤立点形式留在图上，纯增加渲染量。
   * 这里改成语义一致的子图：边定于新闻，关键词只保留在子图内仍然成立的。
   */
  function graphSubset() {
    var inFilter = {};
    filteredNews().forEach(function (it) { inFilter[it.id] = true; });

    var newsNodes = [], present = {};
    state.data.graph.nodes.forEach(function (n) {
      if (n.type === "keyword") return;
      if (inFilter[n.news_id]) { newsNodes.push(n); present[n.id] = true; }
    });

    var kwCount = {}, rawLinks = [];
    state.data.graph.links.forEach(function (l) {
      var s = typeof l.source === "object" ? l.source.id : l.source;
      var t = typeof l.target === "object" ? l.target.id : l.target;
      if (!present[s]) return;
      kwCount[t] = (kwCount[t] || 0) + 1;
      rawLinks.push({ source: s, target: t });
    });

    // 与后端 MIN_KEYWORD_DEGREE 同口径：只留被至少 2 条新闻共享的关键词。
    // 子集太小时（例如只看单一来源）降级为不筛，否则会画成一片孤立点。
    var ids = Object.keys(kwCount);
    var keep = ids.filter(function (k) { return kwCount[k] >= 2; });
    if (!keep.length) keep = ids;
    var keepSet = {};
    keep.forEach(function (k) { keepSet[k] = true; });

    var kwNodes = keep.map(function (kid) {
      var n = state.nodeById.get(kid);
      return n ? Object.assign({}, n, { count: kwCount[kid] }) : null;
    }).filter(Boolean);

    return {
      nodes: newsNodes.concat(kwNodes),
      links: rawLinks.filter(function (l) { return keepSet[l.target]; }),
      newsCount: newsNodes.length,
      filteredCount: Object.keys(inFilter).length,
    };
  }

  function renderGraph() {
    var sub = graphSubset();
    window.GraphView.render(sub.nodes, sub.links, {
      onNewsClick: function (node) { newsDrawer(state.newsById[node.news_id]); },
      onKeywordClick: function (node) { keywordDrawer(node.label); },
      onBudgetCut: function (cut) { renderGraphNotice(cut, sub); },
    });
  }

  /* 图谱提示条：把「为什么图上的点比列表少」直接写在画布上，
   * 而不是让使用者以为数据丢了。文案数字都来自真实的 data.json。 */
  function renderGraphNotice(cut, sub) {
    var box = $("graphNotice");
    var w = (state.data.meta && state.data.meta.window) || {};
    var lines = [];
    if (cut) {
      lines.push("当前筛选命中 " + cut.total + " 个节点，超出单屏可读范围；已按记忆强度只画最强的 "
        + cut.shown + " 个（省略 " + cut.cut + " 个）。缩小时间范围可以看到更多细节。");
    } else if (sub.filteredCount > sub.newsCount) {
      lines.push("当前筛选的 " + sub.filteredCount + " 条资讯里，有 "
        + (sub.filteredCount - sub.newsCount) + " 条已超出图谱记忆窗口（近 "
        + (w.graph_days || 7) + " 天），不再进图；它们在资讯流中仍可阅读。");
    }
    if (w.graph_news_forgotten > 0) {
      lines.push("本轮按记忆强度遗忘了 " + w.graph_news_forgotten
        + " 条、关键词 " + w.graph_keywords_forgotten + " 个。");
    }
    box.hidden = !lines.length;
    box.textContent = lines.join(" ");
  }

  /* 从资讯流/速读点关键词跳图谱：当前筛选里没有这个词时，
   * 自动放宽时间范围再画一次，避免"点了没反应"的假死感。 */
  function showKeywordInGraph(kw) {
    switchView("graph");
    var hit = window.GraphView.hasKeyword ? window.GraphView.hasKeyword(kw) : true;
    if (!hit) {
      state.range = "all";
      document.querySelectorAll(".date-tab").forEach(function (x) {
        x.classList.toggle("active", x.dataset.range === "all");
      });
      renderAll();
    }
    window.GraphView.focusKeyword(kw);
  }

  /* ---------- 事件绑定 ---------- */
  function clearAllFilters() {
    state.range = "today";
    state.query = "";
    state.source = null;
    state.category = null;
    $("searchInput").value = "";
    document.querySelectorAll(".date-tab").forEach(function (x) {
      x.classList.toggle("active", x.dataset.range === "today");
    });
    renderAll();
  }

  function bindEvents() {
    document.querySelectorAll(".view-tab").forEach(function (t) {
      t.addEventListener("click", function () { switchView(t.dataset.view); });
    });
    document.querySelectorAll(".date-tab").forEach(function (t) {
      t.addEventListener("click", function () {
        state.range = t.dataset.range;
        document.querySelectorAll(".date-tab").forEach(function (x) {
          x.classList.toggle("active", x === t);
        });
        renderAll();
      });
    });
    var timer = null;
    $("searchInput").addEventListener("input", function (e) {
      clearTimeout(timer);
      timer = setTimeout(function () {
        state.query = e.target.value;
        renderAll();
      }, 200);
    });
    function clearAll() { clearAllFilters(); }
    $("clearBtn").addEventListener("click", clearAll);
    $("drawerClose").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeDrawer();
    });
    window.addEventListener("resize", function () {
      if (state.view === "graph") window.GraphView.resize();
    });
  }

  function renderAll() {
    renderSourceChips();
    renderDigest();
    if (state.view === "feed") renderFeed();
    else renderGraph();
  }

  /* ---------- 今日洞察（Day 12） ---------- */
  function loadInsight() {
    var url = API_BASE ? API_BASE + "/insight" : "insight.json";
    fetch(url, { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (data) {
        if (!data.available) return;
        renderInsightCard(data);
      })
      .catch(function () { /* 洞察不可用，静默降级 */ });
  }

  function renderInsightCard(data) {
    var box = $("digestCard");
    if (!box || !data.topics || !data.topics.length) return;

    box.hidden = false;
    box.innerHTML = "";

    var header = h("div", "digest-header");
    header.appendChild(h("span", "digest-icon", "💡"));
    header.appendChild(h("span", "digest-label", "今日 AI 洞察"));
    if (data.date) {
      header.appendChild(h("span", "digest-date", data.date));
    }
    box.appendChild(header);

    if (data.summary) {
      box.appendChild(h("p", "digest-summary", data.summary));
    }

    var topicsWrap = h("div", "digest-topics");
    data.topics.forEach(function (topic) {
      var chip = h("button", "digest-topic-chip", topic.title);
      chip.type = "button";
      chip.title = topic.description || "";
      chip.addEventListener("click", function () {
        state.query = topic.title;
        $("searchInput").value = topic.title;
        state.view = "feed";
        switchView("feed");
        renderAll();
      });
      topicsWrap.appendChild(chip);
    });
    box.appendChild(topicsWrap);
  }

  /* ---------- 双数据源：API 优先，失败回落静态 data.json ---------- */
  function loadData() {
    // 如果有 API 基地址，先尝试从 API 获取
    if (API_BASE) {
      return fetch(API_BASE + "/news?limit=200", { cache: "no-cache" })
        .then(function (r) {
          if (!r.ok) throw new Error("API HTTP " + r.status);
          return r.json();
        })
        .then(function (apiData) {
          // 将 API 响应转换为与 data.json 兼容的格式
          state.dataSource = "api";
          return {
            meta: {
              generated_at: new Date().toISOString(),
              total: apiData.total,
              sources: apiData.sources || [],
            },
            news: apiData.items || [],
            graph: { nodes: [], links: [] },
            digest: { topics: [] },
          };
        })
        .catch(function () {
          // API 失败，回落静态文件
          console.warn("[AI 情报站] API 不可用，回落静态 data.json");
          state.dataSource = "static";
          return loadStaticData();
        });
    }
    // 无 API 配置，直接用静态文件
    state.dataSource = "static";
    return loadStaticData();
  }

  function loadStaticData() {
    return fetch("data.json", { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
  }

  /* ---------- 启动 ---------- */
  loadData()
    .then(function (data) {
      state.data = data;
      state.newsById = {};
      data.news.forEach(function (it) { state.newsById[it.id] = it; });
      // 图谱节点索引
      state.nodeById = new Map();
      (data.graph.nodes || []).forEach(function (n) { state.nodeById.set(n.id, n); });
      state.kwByNewsId = {};
      (data.graph.links || []).forEach(function (l) {
        var nid = typeof l.source === "object" ? l.source.id : l.source;
        var kid = typeof l.target === "object" ? l.target.id : l.target;
        var kwNode = state.nodeById.get(kid);
        var newsNode = state.nodeById.get(nid);
        if (kwNode && newsNode && newsNode.news_id != null) {
          (state.kwByNewsId[newsNode.news_id] = state.kwByNewsId[newsNode.news_id] || []).push(kwNode.label);
        }
      });
      $("loading").hidden = true;
      renderStatus();
      bindEvents();
      renderAll();
      loadInsight();
    })
    .catch(function (err) {
      $("loading").hidden = true;
      $("loadError").hidden = false;
      $("loadErrorDetail").textContent = String(err);
    });
})();
