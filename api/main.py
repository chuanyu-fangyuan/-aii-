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
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

# 确保项目根目录在 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from api.schemas import (
    NewsItem, NewsListResponse, HealthResponse,
    AskRequest, AskResponse, Citation, StatsResponse,
    TriggerResponse, ReviewListResponse, ReviewAction,
)
from api.deps import get_db
from api.middleware import verify_api_key
import llm


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时确保 schema 就绪。

    容器/全新克隆场景下 data/news.db 可能不存在，若等第一个请求才建表，
    /health 会先报一次错误、健康检查也就失败一次。
    init_sqlite 是幂等的（CREATE TABLE IF NOT EXISTS + 按缺失列 ALTER），
    所以这里放心无条件执行，也替代了单独的 migrate 容器。
    """
    from db import SQLITE_PATH, init_sqlite

    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        init_sqlite(conn)
    finally:
        conn.close()
    yield


app = FastAPI(
    title="AI 情报站 API",
    description="AI 资讯知识库后端服务",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS 配置（Day 5 关键：允许前端跨域访问）
#
# 跨域校验的是「调用方页面」的来源，不是 API 自己的地址 ——
# 所以演示站部署到 Pages 后，只要这里是 github.io 就能通；
# 换成自定义域名/其它托管时，用 ALLOWED_ORIGINS 环境变量追加，不必改代码。
_DEFAULT_ORIGINS = [
    "https://chuanyu-fangyuan.github.io",  # GitHub Pages 线上
    "http://localhost:5500",                 # Live Server
    "http://localhost:8000",                 # 本地 API
    "http://localhost:8765",                 # 本地前端
    "http://127.0.0.1:5500",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8765",
]
_EXTRA_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEFAULT_ORIGINS + _EXTRA_ORIGINS,
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
        # 降级原因打到 stderr：/health 只回状态码，排障时需要知道为什么降级
        print(f"[health] 数据库不可用: {e}", file=sys.stderr)
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
# RAG 问答（Day 10）
# ============================================================

# RAG 提示词与模型：与评测口径保持一致。
# 注意这里必须是 v2 —— Week 3 的对比实验结论是「线上切 v2」（faithfulness 更稳、0 编造），
# 但此前这里仍指向 v1，导致「门禁评 v2、线上跑 v1」，报告的「评测口径与生产一致」并不成立。
RAG_PROMPT_PATH = os.path.join(BASE_DIR, "prompts", "rag_v2.txt")
RAG_MODEL = llm.DEFAULT_MODEL
RAG_TIMEOUT = 25


def _load_rag_prompt():
    with open(RAG_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _build_context(results):
    parts = []
    for i, r in enumerate(results, 1):
        summary = r.ai_summary_zh or "(无摘要)"
        cat = f"[{r.ai_category}]" if r.ai_category else ""
        parts.append(f"[{i}] {cat} {r.title}\n    来源: {r.source_name}\n    {summary}")
    return "\n\n".join(parts)


def _verify_citations(answer: str, results):
    """从答案里的 [n] 标记反查引用到的新闻 ID。

    只认落在检索结果范围内的编号，越界编号直接忽略（防止模型编造引用序号）。
    """
    import re

    cited_ids = set()
    for m in re.finditer(r"\[(\d+)\]", answer):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(results):
            cited_ids.add(results[idx].news_id)
    return cited_ids


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest, http_request: Request):
    """AI 问答（公开端点，带每日配额）。

    两点设计说明：
      ① 声明成同步 def 而不是 async def：检索（本地模型推理）与 LLM 调用都是
         阻塞操作，写在 async 里会卡住整个事件循环 —— 一个访客提问 20 秒，
         其他人连 /health 都请求不到。同步函数由 FastAPI 丢进线程池，互不阻塞。
      ② 配额在检索之前判定：额度用尽时不做任何计算、不碰 LLM。
    """
    from api.ratelimit import enforce
    from retrieval import search

    quota = enforce(http_request)
    remaining = quota["remaining"]

    results = search(payload.query, top_k=payload.top_k)
    if not results:
        return AskResponse(
            answer="未找到相关资料，请尝试其他关键词。",
            citations=[],
            remaining_quota=remaining,
        )

    context = _build_context(results)
    template = _load_rag_prompt()
    prompt = template.replace("{context}", context).replace("{query}", payload.query)

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE_DIR, ".env"))
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    if not api_key:
        return AskResponse(
            answer="API Key 未配置，无法调用 AI 服务。",
            citations=[Citation(news_id=r.news_id, title=r.title, link=r.url) for r in results[:3]],
            remaining_quota=remaining,
        )

    # 统一走 llm.chat：请求、超时、计量、trace 一套逻辑（Day 25 收口）
    out = llm.chat(
        [{"role": "user", "content": prompt}],
        purpose="ask",
        model=RAG_MODEL,
        temperature=0.3,
        max_tokens=800,
        timeout=RAG_TIMEOUT,
        api_key=api_key,
    )
    if not out["ok"]:
        return AskResponse(
            answer=f"AI 服务调用失败: {out['error_message']}",
            citations=[Citation(news_id=r.news_id, title=r.title, link=r.url) for r in results[:3]],
            remaining_quota=remaining,
        )
    answer = out["content"]

    cited_ids = _verify_citations(answer, results)
    citations = [
        Citation(news_id=r.news_id, title=r.title, link=r.url)
        for r in results
        if r.news_id in cited_ids
    ]

    if not citations:
        citations = [
            Citation(news_id=r.news_id, title=r.title, link=r.url)
            for r in results[:3]
        ]

    return AskResponse(answer=answer, citations=citations, remaining_quota=remaining)


# ============================================================
# 统计信息
# ============================================================

@app.get("/api/stats", response_model=StatsResponse)
async def stats(days: int = Query(0, ge=0, le=365), db: sqlite3.Connection = Depends(get_db)):
    """库内规模 + LLM 成本看板。

    days=0 表示全量；days=N 只看最近 N 天。成本按官方价目表估算
    （含峰谷与缓存命中价，口径见 db.py 与 llm.py），真实对账以账户账单为准。
    """
    total_news = db.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    ai_analyzed = db.execute(
        "SELECT COUNT(*) FROM news WHERE ai_status = 'done'"
    ).fetchone()[0]

    try:
        summary = llm.stats(days=days or None, conn=db)
    except sqlite3.OperationalError:
        # llm_traces 表可能还没建（旧库/首次启动）
        summary = {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_yuan": 0.0,
            "error_calls": 0, "avg_cost_per_call_yuan": 0.0, "by_purpose": [], "daily": [],
        }

    return StatsResponse(
        total_news=total_news,
        ai_analyzed=ai_analyzed,
        total_traces=summary["calls"],
        total_cost_yuan=round(summary["cost_yuan"], 6),
        total_input_tokens=summary["input_tokens"],
        total_output_tokens=summary["output_tokens"],
        error_traces=summary.get("error_calls", 0),
        avg_cost_per_call_yuan=summary.get("avg_cost_per_call_yuan", 0.0),
        window_days=days,
        by_purpose=summary.get("by_purpose", []),
        daily=summary.get("daily", []),
        cost_note=summary.get("unit_note", ""),
        ask_quota=_quota_snapshot(db),
    )


def _quota_snapshot(db: sqlite3.Connection) -> dict:
    """公开配额使用情况（不含任何 IP 信息）"""
    from api.ratelimit import get_quota

    snap = get_quota().snapshot()
    snap.pop("ip_used", None)
    snap.pop("ip_remaining", None)
    return snap


# ============================================================
# 今日洞察（Day 12）
# ============================================================

INSIGHT_PATH = os.path.join(BASE_DIR, "data", "insight.json")


@app.get("/insight")
async def get_insight():
    if not os.path.exists(INSIGHT_PATH):
        return {"available": False, "message": "暂无今日洞察"}

    with open(INSIGHT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {"available": True, **data}


# ============================================================
# HITL 审核（Day 17）
# ============================================================

@app.get("/reviews", response_model=ReviewListResponse)
async def list_reviews(
    status: str = Query("pending", description="筛选状态：pending/approved/rejected/all"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    """获取待审核列表"""
    if status == "all":
        where = ""
        params = []
    else:
        where = "WHERE status = ?"
        params = [status]

    total = db.execute(f"SELECT COUNT(*) FROM pending_review {where}", params).fetchone()[0]

    rows = db.execute(
        f"""SELECT id, news_id, review_type, original_value, suggested_value,
                   reason, status, reviewer_note, created_at, reviewed_at
            FROM pending_review {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()

    items = [dict(r) for r in rows]
    return ReviewListResponse(total=total, items=items)


@app.post("/review/{review_id}")
async def process_review(
    review_id: int,
    action: ReviewAction,
    db: sqlite3.Connection = Depends(get_db),
):
    """处理审核（approve/reject）"""
    if action.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action 必须是 approve 或 reject")

    row = db.execute("SELECT * FROM pending_review WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="审核记录不存在")

    # 更新审核状态
    db.execute(
        """UPDATE pending_review
           SET status = ?, reviewer_note = ?, reviewed_at = datetime('now')
           WHERE id = ?""",
        (action.action, action.note, review_id),
    )

    # 如果 approve，将建议值应用到新闻
    if action.action == "approve" and row["suggested_value"]:
        review_type = row["review_type"]
        news_id = row["news_id"]
        suggested = row["suggested_value"]

        if review_type == "category":
            db.execute("UPDATE news SET ai_category = ? WHERE id = ?", (suggested, news_id))
        elif review_type == "summary":
            db.execute("UPDATE news SET ai_summary_zh = ? WHERE id = ?", (suggested, news_id))
        elif review_type == "verification":
            db.execute("UPDATE news SET verification = ? WHERE id = ?", (suggested, news_id))

    db.commit()

    return {"success": True, "review_id": review_id, "action": action.action}


@app.post("/reviews/submit")
async def submit_review(
    news_id: int = Query(..., description="新闻 ID"),
    review_type: str = Query(..., description="审核类型：category/summary/verification"),
    suggested_value: str = Query(..., description="建议值"),
    reason: str = Query("", description="原因"),
    db: sqlite3.Connection = Depends(get_db),
):
    """提交新的审核请求"""
    row = db.execute("SELECT id, title FROM news WHERE id = ?", (news_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="新闻不存在")

    cursor = db.execute(
        """INSERT INTO pending_review (news_id, review_type, original_value, suggested_value, reason, status)
           VALUES (?, ?, ?, ?, ?, 'pending')""",
        (news_id, review_type, row["title"], suggested_value, reason),
    )
    db.commit()

    return {"success": True, "review_id": cursor.lastrowid}


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
