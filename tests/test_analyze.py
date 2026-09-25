"""分析流水线测试（Week 1 核心：候选筛选 → Prompt → LLM → 校验 → 落库）

网络一律用假对象顶替，测试不花 LLM 费用、不依赖外网。
重点覆盖两块容易出错的逻辑：
  1. 候选筛选的 HN 噪声过滤（1 分 0 评论的帖子不该浪费一次 LLM 调用）
  2. LLM 返回值校验（分类/重要性/可信度越界时必须收敛到合法值）
"""

import json
import sqlite3
import sys
import urllib.error
import os

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import analyze  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_llm_db(monkeypatch, tmp_path):
    """把 llm 的埋点落库路径指到临时库。

    analyze.call_deepseek 现在委托给 llm.chat，而 llm.chat 每次都会写 llm_traces；
    不隔离的话单测会往 data/news.db 里灌测试数据（并最终被提交上去）。
    """
    db_file = tmp_path / "llm_traces.db"
    c = sqlite3.connect(db_file)
    c.row_factory = sqlite3.Row
    sys.path.insert(0, BASE_DIR)
    from db import init_sqlite

    init_sqlite(c)
    c.close()

    import llm

    monkeypatch.setattr(llm, "SQLITE_PATH", str(db_file))
    return db_file


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "analyze.db")
    c.row_factory = sqlite3.Row
    c.executescript(
        """CREATE TABLE news (
               id INTEGER PRIMARY KEY AUTOINCREMENT, url_hash TEXT UNIQUE, title_hash TEXT,
               title TEXT, url TEXT, summary TEXT DEFAULT '', source_id TEXT, source_name TEXT,
               published_at TEXT, fetched_at TEXT, ai_category TEXT, ai_summary_zh TEXT,
               importance INTEGER DEFAULT 0, verification TEXT, verification_note TEXT,
               entities_json TEXT DEFAULT '[]', ai_status TEXT DEFAULT 'pending');
           CREATE TABLE ai_errors (
               id INTEGER PRIMARY KEY AUTOINCREMENT, news_id INTEGER, error_type TEXT,
               error_message TEXT, retry_count INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')));
           CREATE TABLE llm_traces (
               id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT, purpose TEXT,
               input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
               latency_ms INTEGER DEFAULT 0, cost_yuan REAL DEFAULT 0,
               status TEXT DEFAULT 'ok', news_id INTEGER, created_at TEXT DEFAULT (datetime('now')));"""
    )
    yield c
    c.close()


def add_news(conn, title="标题", summary="摘要", source_id="hackernews",
             published_hours_ago=1, ai_status="pending"):
    conn.execute(
        """INSERT INTO news (url_hash, title_hash, title, url, summary, source_id, source_name,
                             published_at, ai_status)
           VALUES (?, ?, ?, 'https://e.com/x', ?, ?, 'src', datetime('now', ?), ?)""",
        (f"h{title}", f"t{title}", title, summary, source_id,
         f"-{published_hours_ago} hours", ai_status),
    )
    conn.commit()


class TestBuildPrompt:
    def test_fills_template_fields(self, monkeypatch, tmp_path):
        tpl = tmp_path / "tpl.txt"
        tpl.write_text("标题：{title}\n来源：{source_name}\n摘要：{summary}\n时间：{published_at}",
                       encoding="utf-8")
        monkeypatch.setattr(analyze, "PROMPT_TEMPLATE_PATH", str(tpl))

        prompt = analyze.build_prompt("新模型发布", "很长的摘要", "Hacker News", "2026-09-23T00:00:00Z")

        assert "新模型发布" in prompt and "Hacker News" in prompt and "很长的摘要" in prompt

    def test_missing_published_at_marked_unknown(self, monkeypatch, tmp_path):
        """时间不能凭空编：缺失时写「未知」，避免模型自行补一个日期"""
        tpl = tmp_path / "tpl.txt"
        tpl.write_text("时间：{published_at}", encoding="utf-8")
        monkeypatch.setattr(analyze, "PROMPT_TEMPLATE_PATH", str(tpl))

        assert "未知" in analyze.build_prompt("t", "", "s", None)

    def test_shipped_template_is_formattable(self):
        """线上模板必须能被 format 填充，缺占位符会在每次调用时炸"""
        prompt = analyze.build_prompt("t", "s", "src", "2026-09-23")
        assert "t" in prompt and len(prompt) > 50


class TestCandidateFiltering:
    def test_skips_already_done(self, conn):
        add_news(conn, title="已分析", ai_status="done")
        assert analyze.get_candidates(conn) == []

    def test_skips_old_items(self, conn):
        add_news(conn, title="八天前", published_hours_ago=8 * 24)
        assert analyze.get_candidates(conn) == []

    def test_keeps_low_score_hn_items_out(self, conn):
        """1 分 0 评论的 HN 新帖不进分析队列（省下的是真金白银）"""
        add_news(conn, title="冷门帖", summary="Hacker News 新帖 · 1 分 · 0 评论")
        assert analyze.get_candidates(conn) == []

    def test_keeps_hn_items_above_score_threshold(self, conn):
        add_news(conn, title="热帖", summary="Hacker News 热帖 · 42 分 · 10 评论")
        add_news(conn, title="刚好 5 分", summary="Hacker News 新帖 · 5 分 · 0 评论")
        titles = {c["title"] for c in analyze.get_candidates(conn)}
        assert titles == {"热帖", "刚好 5 分"}

    def test_other_sources_not_subject_to_score_filter(self, conn):
        add_news(conn, title="媒体稿", summary="常规摘要", source_id="techcrunch")
        assert len(analyze.get_candidates(conn)) == 1

    def test_limit_is_applied(self, conn):
        for i in range(5):
            add_news(conn, title=f"批量{i}", summary="Hacker News 热帖 · 30 分 · 1 评论")
        assert len(analyze.get_candidates(conn, limit=2)) == 2


class TestStatusWrites:
    def test_mark_done_persists_all_fields(self, conn):
        add_news(conn, title="待写")
        news_id = conn.execute("SELECT id FROM news").fetchone()[0]

        analyze.mark_done(conn, news_id, {
            "category": "模型", "summary_zh": "中文摘要", "importance": 4,
            "verification": "confirmed", "verification_note": "官方公告",
            "entities": ["OpenAI"],
        })

        row = conn.execute("SELECT * FROM news WHERE id = ?", (news_id,)).fetchone()
        assert row["ai_status"] == "done"
        assert row["ai_category"] == "模型"
        assert row["importance"] == 4
        assert json.loads(row["entities_json"]) == ["OpenAI"]

    def test_mark_done_uses_defaults_for_missing_keys(self, conn):
        add_news(conn, title="字段缺失")
        news_id = conn.execute("SELECT id FROM news").fetchone()[0]

        analyze.mark_done(conn, news_id, {})

        row = conn.execute("SELECT * FROM news WHERE id = ?", (news_id,)).fetchone()
        assert row["ai_category"] == "其他"
        assert row["verification"] == "unverified"

    def test_mark_analyzing_and_mark_error(self, conn):
        add_news(conn, title="状态流转")
        news_id = conn.execute("SELECT id FROM news").fetchone()[0]

        analyze.mark_analyzing(conn, news_id)
        assert conn.execute("SELECT ai_status FROM news WHERE id = ?", (news_id,)).fetchone()[0] == "analyzing"

        analyze.mark_error(conn, news_id)
        assert conn.execute("SELECT ai_status FROM news WHERE id = ?", (news_id,)).fetchone()[0] == "error"

    def test_log_error_truncates_long_message(self, conn):
        add_news(conn, title="报错")
        news_id = conn.execute("SELECT id FROM news").fetchone()[0]

        analyze.log_error(conn, news_id, "api_error", "x" * 2000, retry_count=2)

        row = conn.execute("SELECT * FROM ai_errors").fetchone()
        assert len(row["error_message"]) == 500
        assert row["error_type"] == "api_error"

    def test_log_trace_records_cost(self, conn):
        """log_trace 现在委托给 llm.record_trace：费用由 token 数按官方价目算，
        调用方传进来的 cost 参数不再被采用（避免两处口径不一致）。"""
        analyze.log_trace(conn, "deepseek-chat", "analyze", 1000, 200, 1500, 0.0014, "ok", news_id=None)
        row = conn.execute("SELECT * FROM llm_traces").fetchone()
        assert row["latency_ms"] == 1500
        assert row["input_tokens"] == 1000 and row["output_tokens"] == 200
        assert row["cost_yuan"] > 0


class TestValidateResult:
    def test_illegal_category_falls_back(self):
        assert analyze.validate_result({"category": "不存在的分类"})["category"] == "其他"

    def test_legal_category_kept(self):
        assert analyze.validate_result({"category": "开源"})["category"] == "开源"

    @pytest.mark.parametrize("raw,expected", [(0, 1), (99, 5), ("3", 3), ("abc", 1), (None, 1)])
    def test_importance_is_clamped(self, raw, expected):
        assert analyze.validate_result({"importance": raw})["importance"] == expected

    def test_illegal_verification_falls_back(self):
        assert analyze.validate_result({"verification": "rumor"})["verification"] == "unverified"

    def test_entities_limited_to_five(self):
        result = analyze.validate_result({"entities": ["a", "b", "c", "d", "e", "f"]})
        assert result["entities"] == ["a", "b", "c", "d", "e"]

    def test_non_list_entities_becomes_empty(self):
        assert analyze.validate_result({"entities": "OpenAI"})["entities"] == []

    def test_summary_is_string(self):
        assert isinstance(analyze.validate_result({})["summary_zh"], str)


class TestCallDeepSeek:
    """用假的 urlopen 顶替网络：分别覆盖成功、HTTP 错误、非 JSON、超时四条路径"""

    def _patch(self, monkeypatch, fn):
        monkeypatch.setattr("urllib.request.urlopen", fn)

    def test_success_parses_content_and_usage(self, monkeypatch):
        payload = {
            "choices": [{"message": {"content": json.dumps({"category": "模型", "summary_zh": "摘要"})}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        }

        class FakeResp:
            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        self._patch(monkeypatch, lambda *a, **k: FakeResp())
        out = analyze.call_deepseek("prompt", "sk-test")

        assert out["ok"] is True
        assert out["result"]["category"] == "模型"
        assert out["input_tokens"] == 120 and out["output_tokens"] == 30

    def test_http_error_reports_status_and_body(self, monkeypatch):
        def raise_http(*a, **k):
            raise urllib.error.HTTPError(
                "https://api.deepseek.com", 429, "rate limited", {}, None
            )

        self._patch(monkeypatch, raise_http)
        out = analyze.call_deepseek("prompt", "sk-test")

        assert out["ok"] is False
        assert out["error_type"] == "api_error"
        assert "429" in out["error_message"]

    def test_non_json_content_is_flagged(self, monkeypatch):
        payload = {"choices": [{"message": {"content": "抱歉，我不能"} }]}

        class FakeResp:
            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        self._patch(monkeypatch, lambda *a, **k: FakeResp())
        out = analyze.call_deepseek("prompt", "sk-test")

        assert out["ok"] is False
        assert out["error_type"] == "json_parse"

    def test_timeout_is_classified(self, monkeypatch):
        def raise_timeout(*a, **k):
            raise TimeoutError("timed out")

        self._patch(monkeypatch, raise_timeout)
        out = analyze.call_deepseek("prompt", "sk-test")

        assert out["ok"] is False
        assert out["error_type"] == "timeout"


class TestAnalyzeOneRetry:
    def _news(self):
        return {"title": "标题", "summary": "摘要", "source_name": "src", "published_at": "2026-09-23"}

    def test_success_returns_validated_result(self, monkeypatch):
        monkeypatch.setattr(analyze, "call_deepseek", lambda p, k: {
            "ok": True, "result": {"category": "非法", "importance": 99},
            "input_tokens": 10, "output_tokens": 5, "latency_ms": 100,
        })

        out = analyze.analyze_one(self._news(), "sk-test")

        assert out["success"] is True
        assert out["result"]["category"] == "其他"
        assert out["result"]["importance"] == 5
        assert out["retries"] == 0

    def test_retries_then_succeeds(self, monkeypatch):
        calls = {"n": 0}

        def flaky(prompt, key):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"ok": False, "error_type": "api_error", "error_message": "500",
                        "input_tokens": 0, "output_tokens": 0, "latency_ms": 1}
            return {"ok": True, "result": {}, "input_tokens": 1, "output_tokens": 1, "latency_ms": 1}

        monkeypatch.setattr(analyze, "call_deepseek", flaky)
        monkeypatch.setattr(analyze.time, "sleep", lambda _s: None)  # 别真等

        out = analyze.analyze_one(self._news(), "sk-test")

        assert out["success"] is True
        assert out["retries"] == 1

    def test_gives_up_after_max_retries(self, monkeypatch):
        monkeypatch.setattr(analyze, "call_deepseek", lambda p, k: {
            "ok": False, "error_type": "api_error", "error_message": "503",
            "input_tokens": 0, "output_tokens": 0, "latency_ms": 1,
        })
        monkeypatch.setattr(analyze.time, "sleep", lambda _s: None)

        out = analyze.analyze_one(self._news(), "sk-test")

        assert out["success"] is False
        assert out["error_type"] == "api_error"

    def test_json_parse_error_stops_early(self, monkeypatch):
        """返回非 JSON 时换 prompt 也没用，不该烧满 3 次重试"""
        calls = {"n": 0}

        def always_bad(prompt, key):
            calls["n"] += 1
            return {"ok": False, "error_type": "json_parse", "error_message": "bad json",
                    "input_tokens": 0, "output_tokens": 0, "latency_ms": 1}

        monkeypatch.setattr(analyze, "call_deepseek", always_bad)
        monkeypatch.setattr(analyze.time, "sleep", lambda _s: None)

        analyze.analyze_one(self._news(), "sk-test")

        assert calls["n"] == 2  # 第 2 次后 break，不跑满 MAX_RETRIES
