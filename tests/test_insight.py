"""今日洞察模块测试（取数 → 拼摘要 → 调 LLM → 落盘），LLM 与网络全程用假对象替代"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import insight as ins  # noqa: E402


def make_conn(tmp_path, rows):
    """建一个只含洞察所需字段的临时库"""
    conn = sqlite3.connect(tmp_path / "insight.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE news (
               id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, ai_category TEXT,
               ai_summary_zh TEXT, source_name TEXT, published_at TEXT,
               fetched_at TEXT, ai_status TEXT DEFAULT 'done', importance INTEGER DEFAULT 0)"""
    )
    for r in rows:
        conn.execute(
            """INSERT INTO news (title, ai_category, ai_summary_zh, source_name,
                                 published_at, fetched_at, ai_status, importance)
               VALUES (:title, :ai_category, :ai_summary_zh, :source_name,
                       :published_at, :fetched_at, :ai_status, :importance)""",
            r,
        )
    conn.commit()
    return conn


def row(title, hours_ago=1, status="done", importance=0, summary="摘要", category="模型"):
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "title": title,
        "ai_category": category,
        "ai_summary_zh": summary,
        "source_name": "Hacker News",
        "published_at": ts,
        "fetched_at": ts,
        "ai_status": status,
        "importance": importance,
    }


class TestGetTodayNews:
    def test_returns_recent_analyzed_rows(self, tmp_path):
        conn = make_conn(tmp_path, [row("新消息", 2), row("更早的消息", 20)])
        news = ins.get_today_news(conn, days=1)
        assert [n["title"] for n in news] == ["新消息", "更早的消息"]
        conn.close()

    def test_excludes_unanalyzed_rows(self, tmp_path):
        conn = make_conn(tmp_path, [row("已完成", 2), row("待分析", 2, status="pending")])
        news = ins.get_today_news(conn, days=1)
        assert [n["title"] for n in news] == ["已完成"]
        conn.close()

    def test_excludes_rows_outside_window(self, tmp_path):
        conn = make_conn(tmp_path, [row("刚刚", 1), row("三天前", 72)])
        news = ins.get_today_news(conn, days=1)
        assert [n["title"] for n in news] == ["刚刚"]
        conn.close()

    def test_orders_by_importance_then_time(self, tmp_path):
        conn = make_conn(tmp_path, [
            row("重要但旧", 20, importance=5),
            row("普通但新", 1, importance=0),
        ])
        news = ins.get_today_news(conn, days=1)
        assert news[0]["title"] == "重要但旧"
        conn.close()


class TestBuildDigest:
    def test_uses_summary_and_truncates(self):
        news = [
            {"title": "标题", "ai_category": "模型", "ai_summary_zh": "概" * 200},
            {"title": "无摘要标题", "ai_category": None, "ai_summary_zh": None},
        ]
        digest = ins.build_news_digest(news)

        lines = digest.split("\n")
        assert lines[0].startswith("1. [模型] ")
        assert len(lines[0]) < 120  # 单条截断到 100 字 + 编号
        assert lines[1] == "2. 无摘要标题"  # 无摘要时回落标题、无分类则不拼 []


class TestGenerateInsight:
    def test_fills_prompt_and_parses_json(self, monkeypatch, tmp_path):
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("日期 {date}\n资讯 {news_digest}", encoding="utf-8")
        monkeypatch.setattr(ins, "PROMPT_PATH", str(prompt_file))

        captured = {}

        def fake_chat(messages, **kwargs):
            # 洞察生成现在走统一入口 llm.chat，这里替换它以免真发请求
            captured.update(messages=messages, **kwargs)
            return {
                "ok": True,
                "content": json.dumps({"topics": [{"title": "芯片"}], "summary": "总览"}),
                "usage": {"input_tokens": 100, "output_tokens": 20, "cache_hit_tokens": 0},
                "latency_ms": 100,
                "cost_yuan": 0.0005,
            }

        monkeypatch.setattr("llm.chat", fake_chat)

        news = [{"title": "T", "ai_category": "模型", "ai_summary_zh": "S"}]
        result = ins.generate_insight("sk-test", news)

        assert result["summary"] == "总览"
        assert captured["purpose"] == "insight"      # 埋点维度要正确，否则看板分不出链路
        assert captured["json_mode"] is True
        assert captured["api_key"] == "sk-test"
        # 模板占位符必须被真实数据替换掉，否则等于把模板原文喂给模型
        sent = captured["messages"][0]["content"]
        assert "{news_digest}" not in sent and "{date}" not in sent
        assert "S" in sent

    def test_failure_raises_with_reason(self, monkeypatch, tmp_path):
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("{date} {news_digest}", encoding="utf-8")
        monkeypatch.setattr(ins, "PROMPT_PATH", str(prompt_file))
        monkeypatch.setattr("llm.chat", lambda *a, **k: {
            "ok": False, "error_type": "api_error", "error_message": "HTTP 500", "latency_ms": 1,
        })

        with pytest.raises(RuntimeError, match="HTTP 500"):
            ins.generate_insight("sk-test", [{"title": "T", "ai_summary_zh": "S"}])


class TestSaveInsight:
    def test_writes_utf8_json(self, monkeypatch, tmp_path):
        target = tmp_path / "nested" / "insight.json"
        monkeypatch.setattr(ins, "INSIGHT_PATH", str(target))

        ins.save_insight({"summary": "中文摘要", "topics": []})

        assert json.loads(target.read_text(encoding="utf-8"))["summary"] == "中文摘要"


class TestRunInsight:
    def test_skips_without_api_key(self, monkeypatch, capsys):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)

        ins.run_insight()

        assert "未配置 DEEPSEEK_API_KEY" in capsys.readouterr().out

    def test_skips_when_too_few_news(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
        conn = make_conn(tmp_path, [row("唯一一条", 1)])
        monkeypatch.setattr(ins, "get_conn", lambda: conn)

        ins.run_insight()

        assert "今日新闻不足 3 条" in capsys.readouterr().out
        conn.close()
