"""Agent 状态图测试

只测「不花钱」的部分：图结构装配、条件边判定逻辑、运行记录落库。
真正调 LLM 的节点由 tests/verify_week3.py 做端到端验收，不进单测（成本与不确定性都不可控）。
"""

import os
import sqlite3
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import agent.graph as g  # noqa: E402


@pytest.fixture
def agent_db(monkeypatch, tmp_path):
    db_file = tmp_path / "agent.db"
    monkeypatch.setattr(g, "SQLITE_PATH", str(db_file))
    g.init_agent_runs_table()
    return db_file


class TestGraphStructure:
    def test_compiles(self):
        assert g.build_graph() is not None

    def test_has_expected_nodes(self):
        nodes = set(g.build_graph().get_graph().nodes)
        assert {"plan", "gather", "verify", "synthesize", "review", "publish"} <= nodes

    def test_regather_loop_is_wired(self):
        """verify 必须能回到 gather —— 这是「补证」能力的结构前提"""
        edges = g.build_graph().get_graph().edges
        pairs = {(e.source, e.target) for e in edges}
        assert ("gather", "verify") in pairs
        assert ("verify", "gather") in pairs
        assert ("verify", "synthesize") in pairs

    def test_publish_is_terminal(self):
        graph = g.build_graph().get_graph()
        targets = {e.target for e in graph.edges}
        assert "publish" in targets  # 有边指向它
        assert not [e for e in graph.edges if e.source == "publish" and e.target != "__end__"]


class TestConditionalEdges:
    def test_regather_when_verification_flagged_and_rounds_remain(self):
        assert g.should_regather({"status": "needs_regather", "verify_count": 0}) == "gather"
        assert g.should_regather({"status": "needs_regather", "verify_count": 1}) == "gather"

    def test_stops_after_two_rounds(self):
        """最多补证 2 轮：防止 verify 与 gather 互相踢皮球把成本烧穿"""
        assert g.should_regather({"status": "needs_regather", "verify_count": 2}) == "synthesize"

    def test_synthesizes_when_verification_passes(self):
        assert g.should_regather({"status": "verified", "verify_count": 0}) == "synthesize"

    def test_missing_fields_default_to_synthesize(self):
        assert g.should_regather({}) == "synthesize"

    def test_review_always_publishes(self):
        assert g.should_revise({}) == "publish"


class TestRunPersistence:
    def test_table_is_created(self, agent_db):
        conn = sqlite3.connect(agent_db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert "agent_runs" in tables

    def test_save_run_inserts_row(self, agent_db):
        run_id = g.save_run({
            "task": "整理今日 AI 要闻",
            "status": "published",
            "report": "报告正文",
            "verify_count": 1,
            "messages": [],
        })

        conn = sqlite3.connect(agent_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()

        assert row["task"] == "整理今日 AI 要闻"
        assert row["status"] == "published"
        assert row["report"] == "报告正文"
        assert row["completed_at"] is not None

    def test_save_run_serializes_messages(self, agent_db):
        from langchain_core.messages import AIMessage

        run_id = g.save_run({"task": "t", "status": "published", "messages": [AIMessage(content="你好")]})

        conn = sqlite3.connect(agent_db)
        payload = conn.execute("SELECT messages_json FROM agent_runs WHERE id = ?", (run_id,)).fetchone()[0]
        conn.close()
        assert "你好" in payload
