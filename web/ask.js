/* AI 问答模块
 * 调用 /ask 端点，渲染回答与引用来源。
 */
(function () {
  "use strict";

  var API_BASE = window.AI_API_BASE || "";

  var askInput = document.getElementById("askInput");
  var askBtn = document.getElementById("askBtn");
  var askResult = document.getElementById("askResult");
  var askLoading = document.getElementById("askLoading");
  var askAnswer = document.getElementById("askAnswer");
  var askCitations = document.getElementById("askCitations");
  var citationsList = document.getElementById("citationsList");
  var askError = document.getElementById("askError");
  var askQuota = document.getElementById("askQuota");

  if (!askInput) return;

  /* 公开演示按 IP 限次（见 api/ratelimit.py）。把剩余次数显式告诉用户，
   * 免得他连问几次后突然被 429 拦住却不知道为什么。 */
  function showQuotaLeft(remaining) {
    if (!askQuota || remaining == null) return;
    askQuota.hidden = false;
    askQuota.textContent = remaining > 0
      ? "公开演示：今日还可提问 " + remaining + " 次（本地部署不限次）"
      : "公开演示：今日额度已用完，明天恢复；本地部署不限次";
  }

  askBtn.addEventListener("click", doAsk);
  askInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") doAsk();
  });

  function doAsk() {
    var query = askInput.value.trim();
    if (!query) return;

    askBtn.disabled = true;
    askBtn.textContent = "思考中…";
    askResult.hidden = false;
    askLoading.hidden = false;
    askAnswer.hidden = true;
    askCitations.hidden = true;
    askError.hidden = true;

    fetch(API_BASE + "/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query, top_k: 5 }),
    })
      .then(function (resp) {
        if (resp.ok) return resp.json();
        // 服务端的错误说明比 "HTTP 429" 有用得多（例如公开演示的配额提示），
        // 所以优先取 detail 字段，取不到再退回报错码。
        return resp.json().catch(function () { return {}; }).then(function (body) {
          throw new Error(body.detail || ("HTTP " + resp.status));
        });
      })
      .then(function (data) {
        askLoading.hidden = true;
        renderAnswer(data);
        showQuotaLeft(data.remaining_quota);
      })
      .catch(function (err) {
        askLoading.hidden = true;
        askError.hidden = false;
        // 连不上（Failed to fetch）与业务报错要分开说明，否则用户不知道是网络还是配额
        var isNetwork = /Failed to fetch|NetworkError|load failed/i.test(err.message);
        askError.textContent = isNetwork
          ? "请求失败：连不上 API 服务（" + API_BASE + "）。公开演示地址见 README；本地使用请先启动 API。"
          : "请求失败：" + err.message;
      })
      .finally(function () {
        askBtn.disabled = false;
        askBtn.textContent = "提问";
      });
  }

  function renderAnswer(data) {
    askAnswer.hidden = false;
    askAnswer.textContent = data.answer || "无回答";

    if (data.citations && data.citations.length > 0) {
      askCitations.hidden = false;
      citationsList.replaceChildren();  // 与 app.js 一致：全站不使用 innerHTML
      data.citations.forEach(function (c, i) {
        var card = document.createElement("a");
        card.className = "citation-card";
        card.href = c.link;
        card.target = "_blank";
        card.rel = "noopener noreferrer";  // 与 app.js 一致：外链都要带全 both

        var num = document.createElement("span");
        num.className = "citation-num";
        num.textContent = "[" + (i + 1) + "]";

        var info = document.createElement("div");
        info.className = "citation-info";

        var title = document.createElement("span");
        title.className = "citation-title";
        title.textContent = c.title;

        var link = document.createElement("span");
        link.className = "citation-link";
        link.textContent = c.link;

        info.appendChild(title);
        info.appendChild(link);
        card.appendChild(num);
        card.appendChild(info);
        citationsList.appendChild(card);
      });
    } else {
      askCitations.hidden = true;
    }
  }
})();
