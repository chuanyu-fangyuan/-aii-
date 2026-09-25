"""前端安全与离线不变量测试

README 的安全章节对外承诺了三件事，这三件事是**可机检**的，所以用测试锁住，
避免哪天顺手一句 `innerHTML = html` 就把承诺打破：

  1. 外部内容（标题/摘要/来源）一律 textContent 渲染 → 全站不出现 innerHTML 等注入面；
  2. 不依赖 CDN → 前端脚本里不出现外部 http(s) 地址（API 地址除外，那是本地/自建服务）；
  3. 图谱数据来自 data.json 的 graph 字段（前端不得自己造数据源）。

这类断言很朴素，但它是「文档与代码一致」的守门人 —— 文档里的承诺一旦没有测试兜着，
过两周就变成假话。
"""

import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE_DIR, "web")


def js_files():
    return [
        os.path.join(WEB_DIR, name)
        for name in sorted(os.listdir(WEB_DIR))
        if name.endswith(".js")
    ]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestNoHtmlInjection:
    def test_no_inner_or_outer_html(self):
        pattern = re.compile(r"\b(innerHTML|outerHTML|insertAdjacentHTML)\b")
        offenders = []
        for path in js_files():
            for lineno, line in enumerate(read(path).splitlines(), 1):
                # 允许注释里提到这个词（比如解释「为什么不用 innerHTML」）
                code = line.split("//")[0]
                if pattern.search(code):
                    offenders.append(f"{os.path.basename(path)}:{lineno}")
        assert not offenders, f"检测到 HTML 注入面，会让富文本成为 XSS 通道：{offenders}"

    def test_no_document_write(self):
        offenders = [
            os.path.basename(p)
            for p in js_files()
            if re.search(r"document\.write\s*\(", read(p))
        ]
        assert not offenders, f"document.write 会绕过 DOM 更新流程：{offenders}"


class TestOfflineCapable:
    def test_no_external_cdn_reference(self):
        """D3 等依赖必须本地打包，否则离线/内网环境图谱会挂掉。

        例外：config.js 是**唯一**允许出现外部地址的地方 —— 它专门承载
        线上 API 地址（由 fetch.py 从环境变量 AI_API_BASE 注入）。
        """
        allowed = ("localhost", "127.0.0.1")
        offenders = []
        for path in js_files():
            if os.path.basename(path) == "config.js":
                continue
            for lineno, line in enumerate(read(path).splitlines(), 1):
                for url in re.findall(r"https?://[^\s'\")]+", line):
                    if not url.startswith(allowed):
                        offenders.append(f"{os.path.basename(path)}:{lineno} {url}")
        assert not offenders, f"前端引用了外部地址，离线不可用：{offenders}"

    def test_config_js_is_the_only_api_base_source(self):
        """地址出口只留一处，避免又有人在 index.html 里硬编码线上地址"""
        config = read(os.path.join(WEB_DIR, "config.js"))
        assert "window.AI_API_BASE" in config
        assert len(re.findall(r"window\.\w+", config)) == 1, "config.js 只该暴露 AI_API_BASE"

    def test_pages_load_config_before_reading_api_base(self):
        """顺序错了就白配：config.js 必须在读取 window.AI_API_BASE 之前加载"""
        for name in ("index.html", "review.html"):
            html = read(os.path.join(WEB_DIR, name))
            assert '<script src="config.js">' in html, f"{name} 未引入 config.js"
            assert html.index("config.js") < html.index("AI_API_BASE"), \
                f"{name} 在读取 AI_API_BASE 之后才加载 config.js，注入的地址不会生效"

    def test_vendored_d3_exists(self):
        vendor = os.path.join(WEB_DIR, "vendor", "d3.v7.min.js")
        assert os.path.exists(vendor), "D3 未本地打包"
        assert os.path.getsize(vendor) > 100_000, "D3 文件疑似不完整"


class TestDataContract:
    def test_frontend_reads_expected_json_files(self):
        """前端只应读构建期产物，不应反过来依赖 API（线上没有后端）"""
        app = read(os.path.join(WEB_DIR, "app.js"))
        assert "data.json" in app
        assert "stats.json" in app

    def test_graph_data_comes_from_data_json(self):
        graph = read(os.path.join(WEB_DIR, "graph.js"))
        assert "graph" in graph
        # 图谱节点/边必须来自已加载的数据，而不是自己拼一份
        assert "nodes" in graph and "links" in graph


class TestExternalLinks:
    def test_blank_target_always_has_noopener_and_noreferrer(self):
        """外链新开窗口时必须同时带 noopener 与 noreferrer。

        `target="_blank"` 但不带 noopener 时，被打开的页面可以通过
        `window.opener` 反向操作本站页面（tabnabbing）。
        """
        offenders = []
        for path in js_files():
            lines = read(path).splitlines()
            for lineno, line in enumerate(lines, 1):
                if "_blank" not in line:
                    continue
                window = " ".join(lines[lineno - 1:lineno + 2])
                if "noopener" not in window or "noreferrer" not in window:
                    offenders.append(f"{os.path.basename(path)}:{lineno}")
        assert not offenders, f"外链缺少 noopener/noreferrer：{offenders}"
