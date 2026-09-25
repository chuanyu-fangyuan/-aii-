"""数据库层测试：schema 初始化与迁移、连接切换、成本计算"""

import importlib.util
import os
import sqlite3
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import db as db_mod  # noqa: E402


class TestCalcCost:
    def test_zero_tokens_costs_nothing(self):
        assert db_mod.calc_cost(0, 0) == 0.0

    def test_cost_is_linear_in_tokens(self):
        assert db_mod.calc_cost(2_000_000, 0) == pytest.approx(db_mod.calc_cost(1_000_000, 0) * 2)

    def test_unit_is_per_million_tokens(self):
        """量纲回归测试：修好之前常量写的是「元/千 token」却按「/百万」计算，少算 1000 倍"""
        cost = db_mod.calc_cost(1_000_000, 0, peak=True)
        assert 1.5 < cost < 3.0  # 峰值百万输入 ≈ $0.30 ≈ ¥2.1

    def test_output_costs_more_than_input(self):
        assert db_mod.calc_cost(0, 1_000_000) > db_mod.calc_cost(1_000_000, 0)

    def test_cache_hit_is_much_cheaper(self):
        assert db_mod.calc_cost(1_000_000, 0, cache_hit_tokens=1_000_000) < 0.1

    def test_peak_is_double_offpeak(self):
        peak = db_mod.calc_cost(1_000_000, 1_000_000, peak=True)
        off = db_mod.calc_cost(1_000_000, 1_000_000, peak=False)
        assert peak == pytest.approx(off * 2, rel=1e-6)

    def test_usd_estimate_matches_official_table(self):
        usd = db_mod.estimate_cost_usd(1_000_000, 1_000_000, peak=True)
        assert usd == pytest.approx(0.30 + 1.20)


class TestSchemaInit:
    def test_creates_all_tables(self, tmp_path):
        conn = sqlite3.connect(tmp_path / "new.db")
        db_mod.init_sqlite(conn)

        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"news", "update_runs", "ai_errors", "llm_traces", "pending_review"} <= tables
        conn.close()

    def test_is_idempotent(self, tmp_path):
        conn = sqlite3.connect(tmp_path / "twice.db")
        for _ in range(3):
            db_mod.init_sqlite(conn)  # 重复执行不应报错（容器/CI 每次启动都会跑）

        count = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        assert count == 0
        conn.close()

    def test_migrates_legacy_news_table(self, tmp_path):
        """老库（Week 1 之前的 news 表）缺少 AI 字段，init_sqlite 要补齐而不是重建"""
        conn = sqlite3.connect(tmp_path / "legacy.db")
        conn.execute(
            "CREATE TABLE news (id INTEGER PRIMARY KEY AUTOINCREMENT, url_hash TEXT NOT NULL UNIQUE, "
            "title_hash TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO news (url_hash, title_hash, title, url) VALUES ('h', 't', '旧记录', 'https://e.com')"
        )
        conn.commit()

        db_mod.init_sqlite(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info(news)")}
        assert {"ai_category", "ai_summary_zh", "importance", "ai_status", "embedding"} <= cols
        # 关键：迁移不能丢数据
        assert conn.execute("SELECT title FROM news").fetchone()[0] == "旧记录"
        conn.close()


class TestConnectionSwitching:
    def test_defaults_to_sqlite(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert db_mod.get_database_url() is None
        assert db_mod.is_pg() is False

    def test_detects_postgres_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost:5432/news")
        assert db_mod.is_pg() is True

    def test_non_postgres_url_falls_back_to_sqlite(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "mysql://localhost/news")
        assert db_mod.is_pg() is False

    def test_get_sqlite_conn_creates_parent_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(db_mod, "SQLITE_PATH", str(tmp_path / "nested" / "news.db"))
        conn = db_mod.get_sqlite_conn()
        assert os.path.isdir(tmp_path / "nested")
        assert conn.row_factory is sqlite3.Row
        conn.close()

    def test_get_conn_returns_closable_sqlite_handle(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(db_mod, "SQLITE_PATH", str(tmp_path / "get_conn.db"))
        conn = db_mod.get_conn()
        conn.execute("SELECT 1")
        db_mod.close_conn(conn)  # 不应抛异常

    def test_pg_pool_reports_missing_driver(self, monkeypatch):
        """未装 psycopg2 时给出明确报错，而不是 ImportError 直接冒出去"""
        if importlib.util.find_spec("psycopg2") is not None:
            pytest.skip("本环境装了 psycopg2，无法验证缺驱动分支")

        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/news")
        monkeypatch.setattr(db_mod, "_pg_pool", None)
        with pytest.raises(RuntimeError, match="psycopg2"):
            db_mod.get_pg_pool()
