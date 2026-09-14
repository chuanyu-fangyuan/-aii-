/* AI 情报站 - 关系图谱（Obsidian 风格）
 * 力导向布局：新闻节点（蓝）+ 关键词节点（橙，按关联数放大）。
 * 交互：拖拽、缩放、悬停高亮关联、点击打开详情抽屉。
 */
(function () {
  "use strict";

  var svg, gRoot, simulation, currentNodes = [], currentLinks = [];
  var handlers = {};
  var focusedKw = null;
  var zoomBehavior;

  function container() { return document.getElementById("graphView"); }

  function size() {
    var c = container();
    return { w: c.clientWidth, h: c.clientHeight };
  }

  function kwRadius(d) { return Math.min(6 + (d.count || 1) * 1.6, 16); }
  function newsRadius() { return 4.5; }

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

  function render(nodes, links, opts) {
    handlers = opts || {};
    var dim = size();
    currentNodes = nodes.map(function (d) { return Object.assign({}, d); });
    currentLinks = links.map(function (d) { return Object.assign({}, d); });

    d3.select("#graphSvg").selectAll("*").remove();
    svg = d3.select("#graphSvg")
      .attr("viewBox", [0, 0, dim.w, dim.h]);

    gRoot = svg.append("g");

    zoomBehavior = d3.zoom()
      .scaleExtent([0.3, 4])
      .on("zoom", function (e) { gRoot.attr("transform", e.transform); });
    svg.call(zoomBehavior);

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
      .attr("fill-opacity", function (d) { return d.type === "keyword" ? 0.9 : 0.8; })
      .attr("stroke", "#14161a")
      .attr("stroke-width", 1.5);

    // 关键词常驻标签；新闻标签默认隐藏，高亮时显示
    var label = node.append("text")
      .text(function (d) {
        if (d.type === "keyword") return d.label;
        return d.label.length > 26 ? d.label.slice(0, 25) + "…" : d.label;
      })
      .attr("x", function (d) { return (d.type === "keyword" ? kwRadius(d) : newsRadius()) + 5; })
      .attr("y", 4)
      .attr("font-size", function (d) { return d.type === "keyword" ? 12 : 11; })
      .attr("fill", function (d) { return d.type === "keyword" ? "#e8eaf0" : "#9aa1b0"; })
      .attr("pointer-events", "none")
      .style("visibility", function (d) { return d.type === "keyword" ? "visible" : "hidden"; });

    node.append("title").text(function (d) {
      return d.type === "keyword"
        ? "关键词：" + d.label + "（" + (d.count || 0) + " 条相关）"
        : d.label;
    });

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
      label.style("visibility", function (n) {
        if (n.type === "keyword") return "visible";
        return on && (n.id === d.id || rel[n.id]) ? "visible" : "hidden";
      });
    }

    node
      .on("mouseenter", function (e, d) { highlight(d, true); })
      .on("mouseleave", function (e, d) { highlight(d, false); })
      .on("click", function (e, d) {
        e.stopPropagation();
        if (d.type === "keyword") handlers.onKeywordClick && handlers.onKeywordClick(d);
        else handlers.onNewsClick && handlers.onNewsClick(d);
      });
    svg.on("click", function () { /* 点空白仅取消高亮 */ });

    simulation = d3.forceSimulation(currentNodes)
      .force("link", d3.forceLink(currentLinks).id(function (d) { return d.id; }).distance(70).strength(0.6))
      .force("charge", d3.forceManyBody().strength(-180))
      .force("center", d3.forceCenter(dim.w / 2, dim.h / 2))
      .force("collide", d3.forceCollide().radius(function (d) {
        return (d.type === "keyword" ? kwRadius(d) : newsRadius()) + 14;
      }))
      .on("tick", function () {
        link
          .attr("x1", function (d) { return d.source.x; })
          .attr("y1", function (d) { return d.source.y; })
          .attr("x2", function (d) { return d.target.x; })
          .attr("y2", function (d) { return d.target.y; });
        node.attr("transform", function (d) { return "translate(" + d.x + "," + d.y + ")"; });
      });

    if (focusedKw) {
      var kw = focusedKw;
      focusedKw = null;
      setTimeout(function () { focusKeyword(kw); }, 350);
    }
  }

  function focusKeyword(labelText) {
    var dim = size();
    var target = currentNodes.find(function (n) {
      return n.type === "keyword" && n.label === labelText;
    });
    if (!target || !svg) return;
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
  }

  function resize() {
    if (!svg) return;
    var dim = size();
    svg.attr("viewBox", [0, 0, dim.w, dim.h]);
    if (simulation) {
      simulation.force("center", d3.forceCenter(dim.w / 2, dim.h / 2));
      simulation.alpha(0.3).restart();
    }
  }

  // 高亮/淡化的样式类
  var style = document.createElement("style");
  style.textContent =
    "#graphSvg g.dim circle,#graphSvg g.dim text{opacity:.12;transition:opacity .15s}" +
    "#graphSvg line.dim{opacity:.06;transition:opacity .15s}" +
    "#graphSvg g,#graphSvg line{transition:opacity .15s}";
  document.head.appendChild(style);

  window.GraphView = { render: render, resize: resize, focusKeyword: focusKeyword };
})();
