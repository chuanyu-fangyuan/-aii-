"""公开演示配额测试

线上演示站把 /ask 暴露给任何访客，配额就是「成本安全闸」——
所以这里既测计数逻辑，也测它**真的挡在检索与 LLM 之前**（不许先花钱再拒绝）。
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import api.ratelimit as rl  # noqa: E402


class FakeRequest:
    """够用的 Request 替身：只需要 headers 与 client.host"""

    def __init__(self, ip="1.2.3.4", forwarded=None):
        self.headers = {}
        if forwarded:
            self.headers["x-forwarded-for"] = forwarded

        class Client:
            host = ip

        self.client = Client()


@pytest.fixture
def quota(monkeypatch):
    q = rl.DailyQuota(per_ip=5, global_limit=8)
    monkeypatch.setattr(rl, "_quota", q)
    return q


class TestDailyQuota:
    def test_allows_up_to_limit_then_blocks(self, quota):
        for i in range(5):
            result = quota.check_and_consume("1.1.1.1")
            assert result["allowed"] is True, f"第 {i+1} 次应放行"
            assert result["remaining"] == 4 - i

        blocked = quota.check_and_consume("1.1.1.1")
        assert blocked["allowed"] is False
        assert blocked["reason"] == "per_ip"
        assert blocked["remaining"] == 0

    def test_other_ips_unaffected(self, quota):
        for _ in range(5):
            quota.check_and_consume("1.1.1.1")
        assert quota.check_and_consume("2.2.2.2")["allowed"] is True

    def test_global_cap_blocks_even_new_ips(self, quota):
        """换 IP 也刷不穿全局上限 —— 这是防分布式刷量的那道闸"""
        for i in range(8):
            assert quota.check_and_consume(f"10.0.0.{i}")["allowed"] is True

        blocked = quota.check_and_consume("10.0.0.99")
        assert blocked["allowed"] is False
        assert blocked["reason"] == "global"

    def test_counters_reset_on_new_day(self, quota):
        for _ in range(5):
            quota.check_and_consume("1.1.1.1")
        assert quota.check_and_consume("1.1.1.1")["allowed"] is False

        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        assert quota.check_and_consume("1.1.1.1", now=tomorrow)["allowed"] is True

    def test_snapshot_hides_ip_details_by_default(self, quota):
        quota.check_and_consume("1.1.1.1")
        snap = quota.snapshot()
        assert snap["ip_used"] is None and snap["ip_remaining"] is None
        assert snap["global_used"] == 1
        assert snap["per_ip_limit"] == 5


class TestClientIp:
    def test_prefers_first_forwarded_hop(self):
        """线上跑在 Fly 代理后面，真实来源在 X-Forwarded-For 的第一段"""
        req = FakeRequest(ip="172.16.0.1", forwarded="203.0.113.9, 172.16.0.1")
        assert rl.client_ip(req) == "203.0.113.9"

    def test_falls_back_to_socket_peer(self):
        assert rl.client_ip(FakeRequest(ip="198.51.100.7")) == "198.51.100.7"

    def test_handles_missing_client(self):
        class NoClient:
            headers = {}
            client = None

        assert rl.client_ip(NoClient()) == "unknown"


class TestEnforce:
    def test_raises_429_with_human_readable_detail(self, quota):
        for _ in range(5):
            rl.enforce(FakeRequest(ip="9.9.9.9"))

        with pytest.raises(HTTPException) as exc:
            rl.enforce(FakeRequest(ip="9.9.9.9"))

        assert exc.value.status_code == 429
        assert "5 次" in exc.value.detail
        assert exc.value.headers.get("Retry-After")

    def test_global_quota_message_is_distinct(self, quota):
        for i in range(8):
            rl.enforce(FakeRequest(ip=f"8.8.8.{i}"))

        with pytest.raises(HTTPException) as exc:
            rl.enforce(FakeRequest(ip="7.7.7.7"))
        assert "全站" in exc.value.detail


class TestAskEndpointIntegration:
    """端到端：配额必须挡在检索/LLM 之前（拒绝时一分钱都不该花）"""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        from db import init_sqlite

        db_file = tmp_path / "quota.db"
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        init_sqlite(conn)
        conn.close()

        import llm
        from fastapi.testclient import TestClient

        from api.main import app

        monkeypatch.setattr("api.deps.SQLITE_PATH", str(db_file))
        monkeypatch.setattr("db.SQLITE_PATH", str(db_file))
        monkeypatch.setattr("retrieval.SQLITE_PATH", str(db_file))
        monkeypatch.setattr(llm, "SQLITE_PATH", str(db_file))
        monkeypatch.setattr(rl, "_quota", rl.DailyQuota(per_ip=2, global_limit=10))
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setattr(llm, "get_api_key", lambda explicit="": "")

        def no_search(*args, **kwargs):
            raise AssertionError("配额拒绝时不该进入检索（更不该调 LLM）")

        monkeypatch.setattr("retrieval.search", no_search)

        with TestClient(app) as c:
            yield c

    def test_quota_blocks_before_any_work(self, client):
        # 空库 + 配额 2：前两次会走检索（此处被我们替换成断言），
        # 所以直接先把配额耗尽，再验证第 3 次是 429 而不是 500
        import api.ratelimit as rl_mod

        q = rl_mod.get_quota()
        q.check_and_consume("testclient")
        q.check_and_consume("testclient")

        resp = client.post("/ask", json={"query": "AI", "top_k": 3})

        assert resp.status_code == 429
        assert "额度" in resp.json()["detail"]

    def test_quota_visible_in_stats(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        quota_info = resp.json()["ask_quota"]
        assert quota_info["per_ip_limit"] == 2
        assert quota_info["global_limit"] == 10
        assert "ip_used" not in quota_info  # 不外泄他人/IP 维度信息
