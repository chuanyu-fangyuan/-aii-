"""API 端点测试

关键约束：**测试不得触碰生产库**。

早期版本直接对着 `data/news.db` 跑，`test_submit_review` 会真往 `pending_review`
插一行「测试」——这些脏数据会被提交进仓库，还会出现在线上的 HITL 审核页里；
同时在没有写权限的环境（CI 的只读检出、受限沙箱）里会直接报
`sqlite3.OperationalError: attempt to write a readonly database`。
现在统一走 `tmp_db` 夹具：临时库 + 最小种子数据，写完即弃。

另一个副作用是省钱：临时库没有带 embedding 的记录，`/ask` 在检索阶段就返回空，
不会加载嵌入模型、也不会真的调 LLM，CI 里这条用例是零成本且确定的。
"""

import os
import sqlite3
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from fastapi.testclient import TestClient  # noqa: E402
from api.main import app  # noqa: E402
from db import init_sqlite  # noqa: E402


SEED_NEWS = [
    ("hash-a", "t-a", "AI 芯片出货量创新高", "https://example.com/a", "hackernews", "Hacker News", "模型"),
    ("hash-b", "t-b", "开源大模型发布新版本", "https://example.com/b", "techcrunch", "TechCrunch AI", "开源"),
]


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """建一个临时库并让所有数据库入口指向它"""
    db_file = tmp_path / "test_news.db"
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    init_sqlite(conn)
    for url_hash, title_hash, title, url, source_id, source_name, category in SEED_NEWS:
        conn.execute(
            """INSERT INTO news (url_hash, title_hash, title, url, summary, source_id,
                                 source_name, published_at, fetched_at, ai_category, ai_status)
               VALUES (?, ?, ?, ?, '', ?, ?, '2026-09-23T00:00:00Z', '2026-09-23T00:00:00Z', ?, 'done')""",
            (url_hash, title_hash, title, url, source_id, source_name, category),
        )
    conn.commit()
    conn.close()

    # api.deps 每次请求取一次路径；db/retrieval 模块各自持有常量，三处都要指过来
    monkeypatch.setattr("api.deps.SQLITE_PATH", str(db_file))
    monkeypatch.setattr("db.SQLITE_PATH", str(db_file))
    monkeypatch.setattr("retrieval.SQLITE_PATH", str(db_file))
    return db_file


@pytest.fixture
def client(tmp_db):
    # 夹具顺序保证 lifespan 里的建表也落在临时库上
    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["news_count"] == len(SEED_NEWS)


class TestNewsEndpoint:
    def test_list_news(self, client):
        response = client.get("/news?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == len(SEED_NEWS)
        assert len(data["items"]) == len(SEED_NEWS)

    def test_list_news_with_source_filter(self, client):
        response = client.get("/news?source=hackernews&limit=3")
        assert response.status_code == 200
        data = response.json()
        assert data["items"]
        for item in data["items"]:
            assert item["source_id"] == "hackernews"

    def test_list_news_with_category_filter(self, client):
        response = client.get("/news?category=模型&limit=3")
        assert response.status_code == 200
        data = response.json()
        assert data["items"]
        for item in data["items"]:
            assert item["ai_category"] == "模型"


class TestAskEndpoint:
    def test_ask_basic(self, client):
        response = client.post("/ask", json={"query": "AI", "top_k": 3})
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "citations" in data

    def test_ask_empty_query(self, client):
        response = client.post("/ask", json={"query": "", "top_k": 3})
        assert response.status_code == 422  # Validation error


class TestReviewsEndpoint:
    def test_list_reviews(self, client):
        response = client.get("/reviews?status=all")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "items" in data

    def test_submit_review(self, client, tmp_db):
        news_id = client.get("/news?limit=1").json()["items"][0]["id"]

        response = client.post(
            f"/reviews/submit?news_id={news_id}&review_type=category&suggested_value=模型&reason=单测"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "review_id" in data

        # 脏数据只落在临时库：明确校验这一点，防止以后又写回生产库
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT COUNT(*) FROM pending_review").fetchone()[0]
        conn.close()
        assert rows == 1


class TestStatsEndpoint:
    def test_stats(self, client):
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_news" in data
        assert "ai_analyzed" in data
        assert "total_cost_yuan" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
