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

  if (!askInput) return;

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
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        return resp.json();
      })
      .then(function (data) {
        askLoading.hidden = true;
        renderAnswer(data);
      })
      .catch(function (err) {
        askLoading.hidden = true;
        askError.hidden = false;
        askError.textContent = "请求失败：" + err.message + "。请检查 API 服务是否运行。";
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
      citationsList.innerHTML = "";
      data.citations.forEach(function (c, i) {
        var card = document.createElement("a");
        card.className = "citation-card";
        card.href = c.link;
        card.target = "_blank";
        card.rel = "noopener";

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
