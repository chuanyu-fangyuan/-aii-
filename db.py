"""数据库连接层

支持两种模式：
  - SQLite（本地开发/测试）
  - PostgreSQL + pgvector（生产/Docker）

通过环境变量 DATABASE_URL 切换：
  - 未设置 → 使用 SQLite（data/news.db）
  - postgresql://... → 使用 PostgreSQL
"""

import os
import sqlite3
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE_DIR, "data", "news.db")

# PostgreSQL 连接池（延迟初始化）
_pg_pool = None


def get_database_url() -> Optional[str]:
    return os.environ.get("DATABASE_URL")


def is_pg() -> bool:
    url = get_database_url()
    return url is not None and url.startswith("postgresql")


def get_sqlite_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_pg_pool():
    """获取 PostgreSQL 连接池（psycopg2）"""
    global _pg_pool
    if _pg_pool is None:
        try:
            from psycopg2 import pool
            _pg_pool = pool.SimpleConnectionPool(
                1, 10,
                get_database_url(),
            )
        except ImportError:
            raise RuntimeError("PostgreSQL 模式需要 psycopg2: pip install psycopg2-binary")
    return _pg_pool


def get_pg_conn():
    pool = get_pg_pool()
    return pool.getconn()


def release_pg_conn(conn):
    pool = get_pg_pool()
    pool.putconn(conn)


def get_conn():
    """统一入口：根据环境变量返回对应数据库连接"""
    if is_pg():
        return get_pg_conn()
    return get_sqlite_conn()


def close_conn(conn):
    """释放连接"""
    if is_pg():
        release_pg_conn(conn)
    else:
        conn.close()


def init_sqlite(conn: sqlite3.Connection):
    """初始化 SQLite schema（含 AI 字段扩展）

    对于已存在的 news 表，通过 ALTER TABLE 增量添加新字段。
    """
    # 1. 建表（新库场景）
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url_hash TEXT NOT NULL UNIQUE,
            title_hash TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            summary TEXT DEFAULT '',
            source_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            published_at TEXT,
            published_unknown INTEGER NOT NULL DEFAULT 0,
            fetched_at TEXT NOT NULL,
            ai_category TEXT,
            ai_summary_zh TEXT,
            importance INTEGER NOT NULL DEFAULT 0,
            verification TEXT,
            verification_note TEXT,
            entities_json TEXT DEFAULT '[]',
            ai_status TEXT NOT NULL DEFAULT 'pending',
            UNIQUE(title_hash, source_id)
        );
        CREATE TABLE IF NOT EXISTS update_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT NOT NULL,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL,
            fetched INTEGER DEFAULT 0,
            inserted INTEGER DEFAULT 0,
            message TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS ai_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER REFERENCES news(id),
            error_type TEXT NOT NULL,
            error_message TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS llm_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL,
            purpose TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            cost_yuan REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ok',
            news_id INTEGER REFERENCES news(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS pending_review (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER NOT NULL REFERENCES news(id),
            review_type TEXT NOT NULL,
            original_value TEXT,
            suggested_value TEXT,
            reason TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewer_note TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            reviewed_at TEXT
        );
    """)

    # 2. 增量迁移：给已存在的 news 表添加 AI 字段
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(news)").fetchall()}
    migrations = [
        ("ai_category", "ALTER TABLE news ADD COLUMN ai_category TEXT"),
        ("ai_summary_zh", "ALTER TABLE news ADD COLUMN ai_summary_zh TEXT"),
        ("importance", "ALTER TABLE news ADD COLUMN importance INTEGER NOT NULL DEFAULT 0"),
        ("verification", "ALTER TABLE news ADD COLUMN verification TEXT"),
        ("verification_note", "ALTER TABLE news ADD COLUMN verification_note TEXT"),
        ("entities_json", "ALTER TABLE news ADD COLUMN entities_json TEXT DEFAULT '[]'"),
        ("ai_status", "ALTER TABLE news ADD COLUMN ai_status TEXT NOT NULL DEFAULT 'pending'"),
        ("embedding", "ALTER TABLE news ADD COLUMN embedding BLOB"),
    ]
    for col_name, sql in migrations:
        if col_name not in existing_cols:
            conn.execute(sql)
    conn.commit()


# ============================================================
# DeepSeek 定价（用于成本追踪）
# ============================================================
DEEPSEEK_PRICING = {
    "input_per_mtok": 0.001,    # ¥0.001/千 token（缓存命中价）
    "output_per_mtok": 0.002,   # ¥0.002/千 token
}


def calc_cost(input_tokens: int, output_tokens: int) -> float:
    """计算 DeepSeek 调用成本（元）"""
    return (input_tokens / 1_000_000) * DEEPSEEK_PRICING["input_per_mtok"] + \
           (output_tokens / 1_000_000) * DEEPSEEK_PRICING["output_per_mtok"]
