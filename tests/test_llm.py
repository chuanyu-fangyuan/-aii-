"""统一 LLM 入口测试（Day 25）

三条硬约束：
  1. 不联网 —— urlopen 一律替换成假对象；
  2. 不花钱 —— 没有任何真实 LLM 调用；
  3. 不污染生产库 —— llm.SQLITE_PATH 指向临时库（早期 API 测试就因为直连
     data/news.db 写进去 4 行「测试」脏数据，这里一开始就隔离）。
"""

import json
import os
import sqlite3
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import db as db_mod  # noqa: E402
import llm  # noqa: E402


@pytest.fixture
def trace_db(monkeypatch, tmp_path):
    """临时库 + 把 llm 的落库路径指过去"""
    db_file = tmp_path / "traces.db"
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    db_mod.init_sqlite(conn)
    conn.close()

    monkeypatch.setattr(llm, "SQLITE_PATH", str(db_file))
    return db_file


def fake_response(payload):
    class FakeResp:
        def read(self):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return FakeResp()


def ok_payload(content="回答内容", prompt_tokens=1000, completion_tokens=200, cache_hit=0):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "prompt_cache_hit_tokens": cache_hit,
        },
    }


class TestApiKey:
    def test_explicit_key_wins(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
        assert llm.get_api_key("explicit") == "explicit"

    def test_reads_environment(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
        assert llm.get_api_key() == "from-env"


class TestUsageParsing:
    def test_extracts_three_numbers(self):
        metrics = llm.parse_usage({
            "prompt_tokens": 800,
            "completion_tokens": 120,
            "prompt_cache_hit_tokens": 500,
        })
        assert metrics == {"input_tokens": 800, "output_tokens": 120, "cache_hit_tokens": 500}

    def test_missing_usage_is_zeroed(self):
        assert llm.parse_usage(None) == {"input_tokens": 0, "output_tokens": 0, "cache_hit_tokens": 0}

    def test_cache_hit_cannot_exceed_input(self):
        """异常响应里命中量大于输入量时，不能出现负数计费"""
        metrics = llm.parse_usage({"prompt_tokens": 10, "prompt_cache_hit_tokens": 999})
        assert metrics["cache_hit_tokens"] == 10


class TestCostModel:
    def test_cache_hit_is_far_cheaper(self):
        peak = True
        full = db_mod.calc_cost(1_000_000, 0, 0, peak=peak)
        cached = db_mod.calc_cost(1_000_000, 0, 1_000_000, peak=peak)
        assert cached < full
        assert full / cached > 40  # 官方缓存价差约 50 倍

    def test_peak_costs_twice_offpeak(self):
        peak = db_mod.calc_cost(1_000_000, 1_000_000, peak=True)
        off = db_mod.calc_cost(1_000_000, 1_000_000, peak=False)
        assert peak == pytest.approx(off * 2, rel=1e-6)

    def test_unit_is_per_million_tokens(self):
        """量纲回归测试：此前把「元/千 token」当「元/百万 token」用，少算 1000 倍"""
        # 峰值 100 万输入 token = $0.30 ≈ ¥2.13
        cost = db_mod.calc_cost(1_000_000, 0, peak=True)
        assert 1.5 < cost < 3.0

    def test_peak_window_detection(self):
        from datetime import datetime, timezone

        # 2026-09-23 是周三；UTC 02:00 落在峰值时段 01-04
        assert db_mod.is_peak_time(datetime(2026, 9, 23, 2, 0, tzinfo=timezone.utc)) is True
        # 同日 UTC 12:00 是非峰值
        assert db_mod.is_peak_time(datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)) is False
        # 周六整天非峰值
        assert db_mod.is_peak_time(datetime(2026, 9, 26, 2, 0, tzinfo=timezone.utc)) is False


class TestRecordTrace:
    def test_writes_row_and_returns_cost(self, trace_db):
        cost = llm.record_trace("ask", "deepseek-chat", {
            "input_tokens": 1000, "output_tokens": 500, "cache_hit_tokens": 0,
        }, 1234)

        conn = sqlite3.connect(trace_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM llm_traces").fetchone()
        conn.close()

        assert row["purpose"] == "ask"
        assert row["input_tokens"] == 1000
        assert row["latency_ms"] == 1234
        assert cost > 0
        assert row["cost_yuan"] == pytest.approx(cost)

    def test_accepts_raw_usage_dict(self, trace_db):
        llm.record_trace("analyze", "deepseek-chat", {"prompt_tokens": 10, "completion_tokens": 5}, 1)
        conn = sqlite3.connect(trace_db)
        assert conn.execute("SELECT input_tokens FROM llm_traces").fetchone()[0] == 10
        conn.close()


class TestChat:
    def test_success_records_trace(self, trace_db, monkeypatch):
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: fake_response(ok_payload()))

        out = llm.chat([{"role": "user", "content": "hi"}], purpose="ask", api_key="sk-test")

        assert out["ok"] is True
        assert out["content"] == "回答内容"
        assert out["usage"]["input_tokens"] == 1000
        assert out["cost_yuan"] > 0

        conn = sqlite3.connect(trace_db)
        assert conn.execute("SELECT COUNT(*) FROM llm_traces WHERE status='ok'").fetchone()[0] == 1
        conn.close()

    def test_missing_key_fails_without_calling(self, trace_db, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setattr(llm, "get_api_key", lambda explicit="": "")

        def explode(*args, **kwargs):
            raise AssertionError("没有 Key 时不该发起请求")

        monkeypatch.setattr("urllib.request.urlopen", explode)

        out = llm.chat([{"role": "user", "content": "hi"}], purpose="ask")

        assert out["ok"] is False
        assert out["error_type"] == "no_api_key"

    def test_http_error_is_recorded_as_error(self, trace_db, monkeypatch):
        import urllib.error

        def raise_http(*args, **kwargs):
            raise urllib.error.HTTPError("https://api.deepseek.com", 429, "rate limited", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", raise_http)

        out = llm.chat([{"role": "user", "content": "hi"}], purpose="ask", api_key="sk-test")

        assert out["ok"] is False
        assert out["error_type"] == "api_error"
        assert "429" in out["error_message"]

        conn = sqlite3.connect(trace_db)
        assert conn.execute("SELECT COUNT(*) FROM llm_traces WHERE status='error'").fetchone()[0] == 1
        conn.close()

    def test_non_json_response(self, trace_db, monkeypatch):
        class BadResp:
            def read(self):
                return b"<html>not json</html>"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: BadResp())

        out = llm.chat([{"role": "user", "content": "hi"}], purpose="ask", api_key="sk-test")
        assert out["error_type"] == "json_parse"

    def test_timeout_classified(self, trace_db, monkeypatch):
        def raise_timeout(*args, **kwargs):
            raise TimeoutError("timed out")

        monkeypatch.setattr("urllib.request.urlopen", raise_timeout)

        out = llm.chat([{"role": "user", "content": "hi"}], purpose="ask", api_key="sk-test")
        assert out["error_type"] == "timeout"

    def test_missing_choices_field(self, trace_db, monkeypatch):
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: fake_response({"usage": {}}))
        out = llm.chat([{"role": "user", "content": "hi"}], purpose="ask", api_key="sk-test")
        assert out["error_type"] == "bad_response"

    def test_json_mode_sets_response_format(self, trace_db, monkeypatch):
        captured = {}

        def capture(req, timeout=None):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return fake_response(ok_payload())

        monkeypatch.setattr("urllib.request.urlopen", capture)
        llm.chat([{"role": "user", "content": "hi"}], purpose="analyze",
                 api_key="sk-test", json_mode=True)

        assert captured["body"]["response_format"] == {"type": "json_object"}


class TestStats:
    def test_aggregates_by_purpose_and_day(self, trace_db):
        llm.record_trace("analyze", "deepseek-chat",
                         {"input_tokens": 1000, "output_tokens": 500, "cache_hit_tokens": 0}, 10)
        llm.record_trace("analyze", "deepseek-chat",
                         {"input_tokens": 2000, "output_tokens": 100, "cache_hit_tokens": 0}, 10)
        llm.record_trace("ask", "deepseek-chat",
                         {"input_tokens": 300, "output_tokens": 200, "cache_hit_tokens": 0}, 10, status="error")

        out = llm.stats()

        assert out["calls"] == 3
        assert out["input_tokens"] == 3300
        assert out["output_tokens"] == 800
        assert out["error_calls"] == 1
        assert out["cost_yuan"] > 0
        purposes = {p["purpose"]: p for p in out["by_purpose"]}
        assert purposes["analyze"]["calls"] == 2
        assert purposes["ask"]["calls"] == 1
        assert out["daily"] and out["daily"][0]["calls"] == 3

    def test_empty_table_is_zero_not_error(self, trace_db):
        out = llm.stats()
        assert out["calls"] == 0
        assert out["cost_yuan"] == 0
        assert out["avg_cost_per_call_yuan"] == 0

    def test_window_filter(self, trace_db):
        conn = sqlite3.connect(trace_db)
        conn.execute(
            """INSERT INTO llm_traces (model, purpose, input_tokens, output_tokens,
                                       latency_ms, cost_yuan, status, created_at)
               VALUES ('deepseek-chat', 'analyze', 100, 10, 1, 0.1, 'ok', datetime('now', '-30 days'))"""
        )
        conn.commit()
        conn.close()

        llm.record_trace("ask", "deepseek-chat",
                         {"input_tokens": 10, "output_tokens": 1, "cache_hit_tokens": 0}, 1)

        assert llm.stats()["calls"] == 2
        assert llm.stats(days=7)["calls"] == 1


class TestRecost:
    def test_recomputes_historical_rows(self, trace_db):
        conn = sqlite3.connect(trace_db)
        conn.execute(
            """INSERT INTO llm_traces (model, purpose, input_tokens, output_tokens,
                                       latency_ms, cost_yuan, status)
               VALUES ('deepseek-chat', 'analyze', 1000000, 0, 100, 0.000001, 'ok')"""
        )
        conn.commit()
        conn.close()

        updated = llm.recost_traces()
        conn = sqlite3.connect(trace_db)
        fixed = conn.execute("SELECT cost_yuan FROM llm_traces").fetchone()[0]
        conn.close()

        assert updated == 1
        # 百万输入 token 至少也是「分」级，不再是原来的 1e-6
        assert fixed > 1.0


class TestReconcile:
    """对账工具：把控制台账单与本地估算摆在一起，差异必须能被解释"""

    def test_close_estimate_reported_as_consistent(self, trace_db):
        llm.record_trace("analyze", "deepseek-chat",
                         {"input_tokens": 100000, "output_tokens": 20000, "cache_hit_tokens": 0}, 10)
        estimated = llm.stats()["cost_yuan"]

        out = llm.reconcile(round(estimated * 1.05, 6))

        assert out["ratio"] == pytest.approx(1.05, abs=0.01)
        assert "一致" in out["verdict"]

    def test_bill_far_above_estimate_points_to_coverage(self, trace_db):
        """首次对账的真实情形：账单远高于估算，主因是有一半调用没埋点"""
        llm.record_trace("analyze", "deepseek-chat",
                         {"input_tokens": 1000, "output_tokens": 200, "cache_hit_tokens": 0}, 10)

        out = llm.reconcile(0.39)

        assert out["ratio"] > 1.1
        assert "未埋点" in out["verdict"]
        assert out["local_calls"] == 1
        assert out["local_tokens"] == 1200

    def test_estimate_above_bill_points_to_pricing(self, trace_db):
        llm.record_trace("analyze", "deepseek-chat",
                         {"input_tokens": 100000, "output_tokens": 20000, "cache_hit_tokens": 0}, 10)

        out = llm.reconcile(0.000001)
        assert "峰谷" in out["verdict"]

    def test_empty_window_cannot_be_compared(self, trace_db):
        out = llm.reconcile(0.39)
        assert out["ratio"] is None
        assert "无法比较" in out["verdict"]


class TestLangchainHandler:
    def test_callbacks_available_or_empty(self):
        handlers = llm.langchain_callbacks("agent")
        assert isinstance(handlers, list)
        assert len(handlers) in (0, 1)  # 没装 langchain 时降级为空列表

    def test_handler_records_usage(self, trace_db):
        handlers = llm.langchain_callbacks("agent")
        if not handlers:
            pytest.skip("环境没有 langchain")

        class FakeMessage:
            usage_metadata = {
                "input_tokens": 500,
                "output_tokens": 80,
                "input_token_details": {"cache_read": 400},
            }

        class FakeGeneration:
            message = FakeMessage()

        class FakeResult:
            generations = [[FakeGeneration()]]

        handlers[0].on_llm_end(FakeResult())

        conn = sqlite3.connect(trace_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM llm_traces").fetchone()
        conn.close()

        assert row["purpose"] == "agent"
        assert row["input_tokens"] == 500
        assert row["output_tokens"] == 80
        # 命中缓存的 400 个 token 应按便宜档计价：费用应低于全按未命中算
        assert row["cost_yuan"] < db_mod.calc_cost(500, 80, 0)

    def test_handler_records_error(self, trace_db):
        handlers = llm.langchain_callbacks("agent")
        if not handlers:
            pytest.skip("环境没有 langchain")

        handlers[0].on_llm_error(RuntimeError("boom"))

        conn = sqlite3.connect(trace_db)
        assert conn.execute("SELECT status FROM llm_traces").fetchone()[0] == "error"
        conn.close()
