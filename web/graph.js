/* AI 情报站 - 关系图谱（Obsidian 风格）
 * 力导向布局：新闻节点（蓝）+ 关键词节点（橙，按关联数放大）。
 * 交互：拖拽、缩放、悬停高亮关联、点击打开详情抽屉。
 *
 * 规模纪律（数据一直涨，图谱不能跟着一起涨）：
 *   1. 单实例    —— 每次重绘前销毁上一个 simulation，避免多个仿真叠加空转
 *   2. 坐标记忆  —— 同一节点跨重绘复用上次坐标，避免每次筛选都从随机位置"炸开"
 *   3. 元素预算  —— 常驻标签只给关键词，新闻标题走单个悬停浮层，SVG 文本节点大幅减少
 *   4. 预算兜底  —— 节点数超过 MAX_NODES 时按记忆强度截断并明确告知，不静默丢数据
 *   5. 离开即停  —— 切回资讯流时暂停仿真，不在隐藏容器里继续空跑
 */
(function () {
  "use strict";

  var MAX_NODES = 360;         // 渲染预算：超过即按强度截断（后端上限 240+100，通常用不到）
  var HEAVY = 220;             // 超过此规模切换到"省电"物理参数
  var svg, gRoot, simulation, currentNodes = [], currentLinks = [];
  var handlers = {};
  var focusedKw = null;
  var zoomBehavior;
  var posCache = {};           // node id -> {x, y}：跨重绘复用坐标
  var pendingFit = false;      // 只在"一次新布局收敛后"自动取景一次，不打扰用户手动缩放
  var tooltip = null;

  function container() { return document.getElementById("graphView"); }

  function size() {
    var c = container();
    return { w: c.clientWidth, h: c.clientHeight };
  }

  function kwRadius(d) { return Math.min(6 + (d.count || 1) * 1.6, 16); }
  function newsRadius() { return 4.5; }

  // 新闻节点按发布时间着色：越新越亮，呼应"每日更新"
  function newsOpacity(d) {
    var s = typeof d.strength === "number" ? d.strength : null;
    if (s !== null) {
      // 有记忆强度时直接用强度做透明度：越接近遗忘，节点越淡
      return Math.max(0.25, Math.min(1, 0.35 + s * 0.75));
    }
    if (!d.time) return 0.45;
    var days = (Date.now() - new Date(d.time).getTime()) / 864e5;
    if (days <= 1) return 1;
    if (days <= 3) return 0.8;
    if (days <= 7) return 0.6;
    return 0.4;
  }

  function neighborSet(links) {
    var map = {};
    links.forEach(function (l) {
      var s = typeof l.source === "object" ? l.source.id : l.source;
      var t = typeof l.target === "object" ? l.target.id : l.target;
      (map[s] = map[s] || {})[t] = true;
      (map[t] = map[t] || {})[s] = true;
    });
    return map;
  }

  /* ---------- 悬停浮层：替代逐个新闻节点的常驻 <text> ---------- */
  function ensureTooltip() {
    if (tooltip && tooltip.parentNode) return tooltip;
    tooltip = document.createElement("div");
    tooltip.className = "graph-tip";
    tooltip.hidden = true;
    container().appendChild(tooltip);
    return tooltip;
  }
  function showTip(node, x, y) {
    var el = ensureTooltip();
    el.textContent = node.type === "keyword"
      ? node.label + " · " + (node.count || 0) + " 条相关"
      : node.label;
    el.hidden = false;
    var w = el.offsetWidth, h = el.offsetHeight;
    var dim = size();
    el.style.left = Math.max(8, Math.min(x + 12, dim.w - w - 8)) + "px";
    el.style.top = Math.max(8, y - h - 12) + "px";
  }
  function hideTip() { if (tooltip) tooltip.hidden = true; }

  /* 冷启动布点：按网格铺开而不是让 d3 用默认的螺旋初始化。
   * d3 默认把第 i 个节点放在半径 10*√i 处，n 大时外侧节点间距只剩零点几像素，
   * 开局斥力巨大，整张图会先"爆炸"再慢慢飘回来（数千像素的震荡，
   * 既是卡顿来源，也是布局看起来发散的原因）。网格间距 28~64px 起步就温和得多。 */
  function seedColdPositions(nodes, dim) {
    var n = nodes.length;
    if (!n) return;
    var aspect = dim.w / Math.max(dim.h, 1);
    var cols = Math.max(1, Math.ceil(Math.sqrt(n * aspect)));
    var rows = Math.max(1, Math.ceil(n / cols));
    var gapX = Math.min(64, Math.max(28, dim.w / (cols + 1)));
    var gapY = Math.min(64, Math.max(28, dim.h / (rows + 1)));
    var x0 = (dim.w - (cols - 1) * gapX) / 2;
    var y0 = (dim.h - (rows - 1) * gapY) / 2;
    nodes.forEach(function (d, i) {
      var r = Math.floor(i / cols), c = i % cols;
      d.x = x0 + r * gapY + (Math.random() - 0.5) * 8;
      d.y = y0 + c * gapX + (Math.random() - 0.5) * 8;
    });
  }

  function render(nodes, links, opts) {
    handlers = opts || {};
    var dim = size();

    // ★ 单实例：先销毁上一次的仿真。
    // 原实现直接给 simulation 变量重新赋值，旧实例仍在后台以 60fps 继续 tick，
    // 并持续操作已从 DOM 移除的元素。切换视图/改筛选几次后，
    // 会有多个仿真同时运行 —— 这是「越用越卡」的直接原因。
    if (simulation) {
      simulation.on("tick", null).on("end", null);
      simulation.stop();
      simulation = null;
    }

    currentLinks = links.map(function (d) { return Object.assign({}, d); });
    // 渲染预算兜底：正常路径下后端已把节点压在上限内，这里是防呆（例如旧 data.json 未更新）
    var all = nodes.map(function (d) { return Object.assign({}, d); });
    if (all.length > MAX_NODES) {
      // 关键词是图谱的语义骨架，必须保；超出部分优先砍记忆强度最低的新闻节点
      var kws = all.filter(function (d) { return d.type === "keyword"; });
      var news = all.filter(function (d) { return d.type !== "keyword"; });
      news.sort(function (a, b) { return (b.strength || 0) - (a.strength || 0); });
      var room = Math.max(0, MAX_NODES - kws.length);
      var keptNews = news.slice(0, room);
      var keptIds = {};
      keptNews.concat(kws).forEach(function (d) { keptIds[d.id] = true; });
      currentNodes = kws.concat(keptNews);
      currentLinks = currentLinks.filter(function (l) {
        var s = typeof l.source === "object" ? l.source.id : l.source;
        var t = typeof l.target === "object" ? l.target.id : l.target;
        return keptIds[s] && keptIds[t];
      });
      handlers.onBudgetCut && handlers.onBudgetCut({
        total: all.length, shown: currentNodes.length, cut: all.length - currentNodes.length,
      });
    } else {
      currentNodes = all;
      handlers.onBudgetCut && handlers.onBudgetCut(null);
    }

    var heavy = currentNodes.length > HEAVY;

    d3.select("#graphSvg").selectAll("*").remove();
    d3.select("#graphSvg").on(".zoom", null);
    svg = d3.select("#graphSvg").attr("viewBox", [0, 0, dim.w, dim.h]);
    gRoot = svg.append("g");
    zoomBehavior = d3.zoom()
      .scaleExtent([0.3, 4])
      .on("zoom", function (e) { gRoot.attr("transform", e.transform); });
    svg.call(zoomBehavior);

    // 坐标记忆：命中缓存的比例够高才复用，否则视为"冷启动"整体重排
    var cached = 0;
    currentNodes.forEach(function (d) {
      var p = posCache[d.id];
      if (p) { d.x = p.x; d.y = p.y; cached++; }
    });
    var warm = cached >= currentNodes.length * 0.5;
    if (warm && cached < currentNodes.length) {
      // 新出现的节点落在已有布局的中心附近，不要甩到远处再飞回来
      var cx = 0, cy = 0;
      currentNodes.forEach(function (d) { if (d.x != null) { cx += d.x; cy += d.y; } });
      cx = cx / cached; cy = cy / cached;
      currentNodes.forEach(function (d) {
        if (d.x == null) { d.x = cx + (Math.random() - 0.5) * 60; d.y = cy + (Math.random() - 0.5) * 60; }
      });
    } else if (!warm) {
      seedColdPositions(currentNodes, dim);
    }

    var neighbors = neighborSet(currentLinks);

    var link = gRoot.append("g")
      .attr("stroke", "#3a4150")
      .attr("stroke-opacity", 0.55)
      .selectAll("line")
      .data(currentLinks)
      .join("line")
      .attr("stroke-width", 1);

    var node = gRoot.append("g")
      .selectAll("g")
      .data(currentNodes)
      .join("g")
      .attr("cursor", "pointer")
      .call(d3.drag()
        .on("start", function (e, d) {
          if (!e.active) simulation.alphaTarget(0.25).restart();
          d.fx = d.x; d.fy = d.y;
          hideTip();
        })
        .on("drag", function (e, d) { d.fx = e.x; d.fy = e.y; })
        .on("end", function (e, d) {
          if (!e.active) simulation.alphaTarget(0);
          d.fx = null; d.fy = null;
        }));

    // 透明扩大点击/悬停热区，小节点也容易点中
    node.append("circle")
      .attr("r", function (d) { return (d.type === "keyword" ? kwRadius(d) : newsRadius()) + 8; })
      .attr("fill", "transparent");

    node.append("circle")
      .attr("r", function (d) { return d.type === "keyword" ? kwRadius(d) : newsRadius(); })
      .attr("fill", function (d) { return d.type === "keyword" ? "#f0b86e" : "#6e8efb"; })
      .attr("fill-opacity", function (d) { return d.type === "keyword" ? 0.9 : newsOpacity(d); })
      .attr("stroke", "#14161a")
      .attr("stroke-width", 1.5);

    // 常驻标签只给关键词：新闻标题改走悬停浮层。
    // 上千个不可见的 <text> 同样是排版成本，去掉后 DOM 节点数随新闻数不再线性增长。
    var label = node.filter(function (d) { return d.type === "keyword"; })
      .append("text")
      .text(function (d) { return d.label; })
      .attr("x", function (d) { return kwRadius(d) + 5; })
      .attr("y", 4)
      .attr("font-size", 12)
      .attr("fill", "#e8eaf0")
      .attr("pointer-events", "none");

    function highlight(d, on) {
      var rel = neighbors[d.id] || {};
      node.classed("dim", function (n) {
        return on && n.id !== d.id && !rel[n.id];
      });
      link.classed("dim", function (l) {
        var s = typeof l.source === "object" ? l.source.id : l.source;
        var t = typeof l.target === "object" ? l.target.id : l.target;
        return on && s !== d.id && t !== d.id;
      });
      // 高亮时把邻居关键词的标签也显出来（这里只对关键词 text 生效）
      label.attr("opacity", function (n) {
        if (!on) return 1;
        return (n.id === d.id || rel[n.id]) ? 1 : 0.15;
      });
    }

    node
      .on("mouseenter", function (e, d) {
        highlight(d, true);
        var t = d3.pointer(e, container());
        showTip(d, t[0], t[1]);
      })
      .on("mousemove", function (e, d) {
        var t = d3.pointer(e, container());
        showTip(d, t[0], t[1]);
      })
      .on("mouseleave", function (e, d) { highlight(d, false); hideTip(); })
      .on("click", function (e, d) {
        e.stopPropagation();
        hideTip();
        if (d.type === "keyword") handlers.onKeywordClick && handlers.onKeywordClick(d);
        else handlers.onNewsClick && handlers.onNewsClick(d);
      });

    // tick 降频：节点越多，DOM 更新越省（视觉上仍连贯）
    var frameSkip = heavy ? 2 : 1;
    var frame = 0;

    function ticked() {
      if (++frame % frameSkip !== 0) return;
      link
        .attr("x1", function (d) { return d.source.x; })
        .attr("y1", function (d) { return d.source.y; })
        .attr("x2", function (d) { return d.target.x; })
        .attr("y2", function (d) { return d.target.y; });
      node.attr("transform", function (d) { return "translate(" + d.x + "," + d.y + ")"; });
    }

    simulation = d3.forceSimulation(currentNodes)
      .force("link", d3.forceLink(currentLinks).id(function (d) { return d.id; })
        .distance(heavy ? 46 : 70)
        .strength(heavy ? 0.35 : 0.6))
      // distanceMax 截断斥力计算半径：远处节点不再互相计算，复杂度大幅下降
      .force("charge", d3.forceManyBody()
        .strength(heavy ? -90 : -180)
        .distanceMax(heavy ? 200 : Infinity))
      .force("center", d3.forceCenter(dim.w / 2, dim.h / 2))
      // collide 在大图下是最贵的一项（每帧对所有节点做碰撞检测），超阈值直接不做
      .alphaDecay(heavy ? 0.05 : 0.0228)
      .velocityDecay(0.45)
      .on("tick", ticked)
      .on("end", function () {
        rememberPositions();
        if (pendingFit) { pendingFit = false; fitView(true); }
      });

    // 坐标全部命中缓存时布局已经稳定，直接取景即可，不用等收敛
    if (warm) fitView(false);
    else pendingFit = true;

    if (!heavy) {
      simulation.force("collide", d3.forceCollide().radius(function (d) {
        return (d.type === "keyword" ? kwRadius(d) : newsRadius()) + 14;
      }));
    }

    if (focusedKw) {
      var kw = focusedKw;
      focusedKw = null;
      setTimeout(function () { focusKeyword(kw); }, warm ? 120 : 350);
    }
  }

  function rememberPositions() {
    currentNodes.forEach(function (d) {
      if (d.x != null && isFinite(d.x)) posCache[d.id] = { x: d.x, y: d.y };
    });
  }

  /* 自适应取景：布局收敛后把整张图缩放到视口内。
   * 图谱规模被遗忘机制钉住后，"看得全"重新变得可行——
   * 不加这一步，节点云会比视口大得多，看起来像只画了几个点。 */
  function fitView(animate) {
    if (!svg || !currentNodes.length) return;
    var pad = 44, minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    currentNodes.forEach(function (d) {
      if (d.x == null || !isFinite(d.x)) return;
      if (d.x < minX) minX = d.x;
      if (d.x > maxX) maxX = d.x;
      if (d.y < minY) minY = d.y;
      if (d.y > maxY) maxY = d.y;
    });
    if (!isFinite(minX)) return;
    var w = maxX - minX, h = maxY - minY;
    if (w <= 0 && h <= 0) return;
    w = Math.max(w, 1); h = Math.max(h, 1);
    var dim = size();
    // 下限 0.35：矮视口下宁可溢出（可滚轮缩小）也别把节点缩成针尖
    var k = Math.max(0.35, Math.min((dim.w - pad * 2) / w, (dim.h - pad * 2) / h, 1.6));
    if (!isFinite(k) || k <= 0) return;
    var t = d3.zoomIdentity
      .translate(dim.w / 2 - k * (minX + w / 2), dim.h / 2 - k * (minY + h / 2))
      .scale(k);
    if (animate) svg.transition().duration(600).call(zoomBehavior.transform, t);
    else svg.call(zoomBehavior.transform, t);
  }

  function focusKeyword(labelText) {
    var dim = size();
    var target = currentNodes.find(function (n) {
      return n.type === "keyword" && n.label === labelText;
    });
    if (!target || !svg) return false;
    focusedKw = labelText;
    // 等 simulation 稳定后把视角平滑移到该节点
    var tries = 0;
    var iv = setInterval(function () {
      tries++;
      if (target.x == null && tries < 20) return;
      clearInterval(iv);
      var x = target.x == null ? dim.w / 2 : target.x;
      var y = target.y == null ? dim.h / 2 : target.y;
      var t = d3.zoomIdentity.translate(dim.w / 2 - x * 1.4, dim.h / 2 - y * 1.4).scale(1.4);
      svg.transition().duration(500).call(zoomBehavior.transform, t);
      target.fx = x; target.fy = y;
      setTimeout(function () { target.fx = null; target.fy = null; }, 800);
      // 闪烁提示
      d3.selectAll("#graphSvg circle").filter(function (d) { return d.id === target.id; })
        .attr("stroke", "#fff").attr("stroke-width", 2.5)
        .transition().delay(1600).duration(600)
        .attr("stroke", "#14161a").attr("stroke-width", 1.5);
    }, 120);
    return true;
  }

  /* 当前已渲染的节点里有没有这个关键词（调用方据此决定要不要放宽筛选） */
  function hasKeyword(labelText) {
    return currentNodes.some(function (n) {
      return n.type === "keyword" && n.label === labelText;
    });
  }

  function resize() {
    if (!svg) return;
    var dim = size();
    svg.attr("viewBox", [0, 0, dim.w, dim.h]);
    if (simulation) {
      simulation.force("center", d3.forceCenter(dim.w / 2, dim.h / 2));
      // 用较低 alpha 重启：中心点变了需要重排，但没必要从零重跑
      simulation.alpha(0.12).restart();
    }
  }

  /* 离开图谱视图时暂停：容器被 hidden 后仿真还在跑纯属浪费 CPU */
  function pause() {
    if (simulation) {
      simulation.stop();
      rememberPositions();
    }
    hideTip();
  }

  // 高亮/淡化的样式类
  var style = document.createElement("style");
  style.textContent =
    "#graphSvg g.dim circle,#graphSvg g.dim text{opacity:.12;transition:opacity .15s}" +
    "#graphSvg line.dim{opacity:.06;transition:opacity .15s}" +
    "#graphSvg g,#graphSvg line,#graphSvg text{transition:opacity .15s}";
  document.head.appendChild(style);

  window.GraphView = {
    render: render, resize: resize, focusKeyword: focusKeyword, pause: pause,
    hasKeyword: hasKeyword,
  };
})();
