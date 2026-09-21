#!/usr/bin/env python3
"""AI 情报站 - FastAPI 主入口

端点：
  GET  /health          - 健康检查
  GET  /news            - 新闻列表（支持筛选）
  GET  /news/{id}       - 新闻详情
  POST /analyze/trigger - 触发分析（需鉴权）
  GET  /api/stats       - 统计信息

启动：
  uvicorn api.main:app --reload --port 8000
  然后访问 http://localhost:8000/docs
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# 确保项目根目录在 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from api.schemas import (
    NewsItem, NewsListResponse, HealthResponse,
    AskRequest, AskResponse, Citation, StatsResponse,
    TriggerResponse,
)
from api.deps import get_db
from api.middleware import verify_api_key

app = FastAPI(
    title="AI 情报站 API",
    description="AI 资讯知识库后端服务",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 配置（Day 5 关键：允许前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://chuanyu-fangyuan.github.io",  # GitHub Pages 线上
        "http://localhost:5500",                 # Live Server
        "http://localhost:8000",                 # 本地 API
        "http://127.0.0.1:5500",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ============================================================
# 健康检查（无需鉴权）
# ============================================================

@app.get("/health", response_model=HealthResponse)
async def health(db: sqlite3.Connection = Depends(get_db)):
    try:
        count = db.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        return HealthResponse(
            status="ok",
            database="sqlite",
            news_count=count,
        )
    except Exception as e:
        return HealthResponse(
            status="degraded",
            database="sqlite",
            news_count=0,
        )


# ============================================================
# 新闻列表
# ============================================================

@app.get("/news", response_model=NewsListResponse)
async def list_news(
    source: str = Query(None, description="来源筛选"),
    category: str = Query(None, description="AI 分类筛选"),
    days: int = Query(0, ge=0, le=90, description="时间范围（天），0=全部"),
    limit: int = Query(50, ge=1, le=200, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: sqlite3.Connection = Depends(get_db),
):
    conditions = []
    params = []

    if source:
        conditions.append("source_id = ?")
        params.append(source)
    if category:
        conditions.append("ai_category = ?")
        params.append(category)
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conditions.append("COALESCE(published_at, fetched_at) >= ?")
        params.append(cutoff)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    total = db.execute(f"SELECT COUNT(*) FROM news {where}", params).fetchone()[0]

    rows = db.execute(
        f"""SELECT id, title, url, summary, source_id, source_name,
                   published_at, published_unknown, fetched_at,
                   ai_category, ai_summary_zh, importance, verification,
                   verification_note, entities_json
            FROM news {where}
            ORDER BY COALESCE(published_at, fetched_at) DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()

    items = [dict(r) for r in rows]

    # 获取来源列表
    sources = [
        dict(r) for r in db.execute(
            "SELECT source_id, source_name, COUNT(*) as count FROM news GROUP BY source_id"
        ).fetchall()
    ]

    return NewsListResponse(total=total, items=items, sources=sources)


# ============================================================
# 新闻详情
# ============================================================

@app.get("/news/{news_id}", response_model=NewsItem)
async def get_news(news_id: int, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(
        """SELECT id, title, url, summary, source_id, source_name,
                  published_at, published_unknown, fetched_at,
                  ai_category, ai_summary_zh, importance, verification,
                  verification_note, entities_json
           FROM news WHERE id = ?""",
        (news_id,),
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="新闻不存在")

    return dict(row)


# ============================================================
# 触发分析（需鉴权）
# ============================================================

@app.post("/analyze/trigger", response_model=TriggerResponse)
async def trigger_analysis(
    limit: int = Query(0, ge=0, le=100, description="分析条数限制"),
    api_key: str = Depends(verify_api_key),
):
    """触发 AI 分析流水线。需要有效的 API Key。"""
    # 这里只返回待分析数量，实际分析通过 analyze.py 脚本执行
    # 生产环境中可以改为异步任务
    from db import SQLITE_PATH, init_sqlite

    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    init_sqlite(conn)

    # 统计待分析数量
    count = conn.execute(
        """SELECT COUNT(*) FROM news
           WHERE COALESCE(published_at, fetched_at) >= datetime('now', '-7 days')
             AND (ai_status IS NULL OR ai_status != 'done')"""
    ).fetchone()[0]

    conn.close()

    return TriggerResponse(
        status="pending",
        message=f"发现 {count} 条待分析记录。请运行 `python analyze.py --limit {limit or ''}` 执行分析。",
        candidates=count,
    )


# ============================================================
# 统计信息
# ============================================================

@app.get("/api/stats", response_model=StatsResponse)
async def stats(db: sqlite3.Connection = Depends(get_db)):
    total_news = db.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    ai_analyzed = db.execute(
        "SELECT COUNT(*) FROM news WHERE ai_status = 'done'"
    ).fetchone()[0]

    # LLM 调用统计
    try:
        trace_row = db.execute(
            """SELECT COUNT(*) as cnt,
                      COALESCE(SUM(input_tokens), 0) as inp,
                      COALESCE(SUM(output_tokens), 0) as outp,
                      COALESCE(SUM(cost_yuan), 0) as cost
               FROM llm_traces"""
        ).fetchone()
        total_traces = trace_row[0]
        total_input = trace_row[1]
        total_output = trace_row[2]
        total_cost = trace_row[3]
    except sqlite3.OperationalError:
        # llm_traces 表可能还没建
        total_traces = 0
        total_input = 0
        total_output = 0
        total_cost = 0.0

    return StatsResponse(
        total_news=total_news,
        ai_analyzed=ai_analyzed,
        total_traces=total_traces,
        total_cost_yuan=round(total_cost, 6),
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
