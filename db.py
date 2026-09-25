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
from datetime import datetime, timezone
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
#
# 口径来源：官方价目表 https://api-docs.deepseek.com/quick_start/pricing
# （2026-09-23 核对）。注意此前这里的量纲是错的：常量写的是「元/千 token」，
# 计算时却除以 1_000_000，等于把成本少算了 1000 倍 —— 365 次调用的累计费用
# 被记成 ¥0.0003，与真实账单差了几个数量级。
#
# 现在改成按官方表格的三档价格 + 峰谷区分（官方单位是 USD/百万 token）：
#   输入（缓存未命中）  峰值 $0.30 / 非峰值 $0.15
#   输入（缓存命中）    峰值 $0.006 / 非峰值 $0.003
#   输出                峰值 $1.20 / 非峰值 $0.60
# 峰值时段：UTC 周一至周五 01:00-04:00、06:00-10:00；其余时间（含周末与法定节假日）非峰值。
#
# 声明：官方保留调价权，汇率也会浮动，这里的数字只能用于「估算」，
# 真实对账请以 DeepSeek 账户账单为准。
# ============================================================
DEEPSEEK_PRICING_USD = {
    "input_cache_miss": {"peak": 0.30, "offpeak": 0.15},
    "input_cache_hit": {"peak": 0.006, "offpeak": 0.003},
    "output": {"peak": 1.20, "offpeak": 0.60},
}

USD_CNY = 7.1  # 折算汇率（估算值，仅用于把官方美元价换算成人民币展示）

PEAK_HOURS_UTC = ((1, 4), (6, 10))  # 官方峰值时段（UTC，周一至周五）


def is_peak_time(dt: Optional[datetime] = None) -> bool:
    """当前是否处于官方峰值计费时段（决定用 peak 还是 offpeak 单价）"""
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.weekday() >= 5:  # 周末整段非峰值
        return False
    return any(start <= dt.hour < end for start, end in PEAK_HOURS_UTC)


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    cache_hit_tokens: int = 0,
    peak: Optional[bool] = None,
) -> float:
    """按官方价目估算费用（美元）。

    cache_hit_tokens：命中最便宜的缓存档的那部分输入；其余输入按缓存未命中计。
    不传 peak 时自动按当前时间判断峰谷。
    """
    tier = "peak" if (is_peak_time() if peak is None else peak) else "offpeak"
    hit = max(0, min(cache_hit_tokens, input_tokens))
    miss = max(0, input_tokens - hit)

    return (
        miss / 1_000_000 * DEEPSEEK_PRICING_USD["input_cache_miss"][tier]
        + hit / 1_000_000 * DEEPSEEK_PRICING_USD["input_cache_hit"][tier]
        + output_tokens / 1_000_000 * DEEPSEEK_PRICING_USD["output"][tier]
    )


def calc_cost(
    input_tokens: int,
    output_tokens: int,
    cache_hit_tokens: int = 0,
    peak: Optional[bool] = None,
) -> float:
    """计算 DeepSeek 调用成本（人民币，估算）"""
    return estimate_cost_usd(input_tokens, output_tokens, cache_hit_tokens, peak) * USD_CNY
