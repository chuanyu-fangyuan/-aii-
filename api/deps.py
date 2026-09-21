"""FastAPI 依赖注入"""

import os
import sqlite3
from typing import Generator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_PATH = os.path.join(BASE_DIR, "data", "news.db")


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """获取 SQLite 连接（请求级别）

    check_same_thread=False: FastAPI 的依赖注入和端点可能在不同线程执行，
    需要允许跨线程使用连接。每个请求创建独立连接，不存在并发写入冲突。
    """
    conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
