/* AI 情报站 - 前端主逻辑
 * 数据来自 fetch.py 生成的 data.json；所有外部内容均以 textContent 渲染，防 XSS。
 * 时间口径：存储为 UTC ISO，展示统一转为 Asia/Shanghai。
 */
(function () {
  "use strict";

  var TZ = "Asia/Shanghai";
  var state = {
    view: "feed",          // feed | graph
    range: "today",        // today | week | all
    query: "",
    source: null,          // null = 全部来源
    data: null,
    kwByNewsId: {},        // news_id -> [keyword label]
    newsById: {},          // id -> news item
  };

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
      if (q) {
        var hay = (it.title + " " + (it.summary || "")).toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });
  }
  function hasActiveFilter() {
    return state.range !== "today" || !!state.query.trim() || !!state.source;
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
      kwBtn.addEventListener("click", function () {
        switchView("graph");
        window.GraphView.focusKeyword(tp.keyword);
      });
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

      if (it.summary) card.appendChild(h("p", "card-summary", it.summary));

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
          pill.addEventListener("click", function () {
            switchView("graph");
            window.GraphView.focusKeyword(kw);
          });
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
    if (view === "graph") renderGraph();
  }

  function renderGraph() {
    var items = filteredNews();
    var ids = {};
    items.forEach(function (it) { ids["n" + it.id] = true; });
    var g = state.data.graph;
    var nodes = g.nodes.filter(function (n) { return n.type === "keyword" || ids[n.id]; });
    var nodeIds = {};
    nodes.forEach(function (n) { nodeIds[n.id] = true; });
    var links = g.links.filter(function (l) {
      var s = typeof l.source === "object" ? l.source.id : l.source;
      var t = typeof l.target === "object" ? l.target.id : l.target;
      return nodeIds[s] && nodeIds[t];
    });
    window.GraphView.render(nodes, links, {
      onNewsClick: function (node) { newsDrawer(state.newsById[node.news_id]); },
      onKeywordClick: function (node) { keywordDrawer(node.label); },
    });
  }

  /* ---------- 事件绑定 ---------- */
  function clearAllFilters() {
    state.range = "today";
    state.query = "";
    state.source = null;
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

  /* ---------- 启动 ---------- */
  fetch("data.json", { cache: "no-cache" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (data) {
      state.data = data;
      data.news.forEach(function (it) { state.newsById[it.id] = it; });
      // 由图谱边构建 news -> keywords 映射
      data.graph.links.forEach(function (l) {
        var nid = l.source, kid = l.target;
        if (typeof nid === "object") { nid = nid.id; kid = kid.id; }
        var kwNode = data.graph.nodes.find(function (n) { return n.id === kid; });
        var newsNode = data.graph.nodes.find(function (n) { return n.id === nid; });
        if (kwNode && newsNode && newsNode.news_id != null) {
          (state.kwByNewsId[newsNode.news_id] = state.kwByNewsId[newsNode.news_id] || []).push(kwNode.label);
        }
      });
      $("loading").hidden = true;
      renderStatus();
      bindEvents();
      renderAll();
    })
    .catch(function (err) {
      $("loading").hidden = true;
      $("loadError").hidden = false;
      $("loadErrorDetail").textContent = String(err);
    });
})();
