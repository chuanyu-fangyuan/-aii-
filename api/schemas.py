"""Pydantic 模型定义"""

from typing import Optional
from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    id: int
    title: str
    url: str
    summary: str = ""
    source_id: str
    source_name: str
    published_at: Optional[str] = None
    published_unknown: bool = False
    fetched_at: str
    # AI 字段（可选，旧数据可能没有）
    ai_category: Optional[str] = None
    ai_summary_zh: Optional[str] = None
    importance: int = 0
    verification: Optional[str] = None
    verification_note: Optional[str] = None
    entities_json: Optional[str] = "[]"


class NewsListResponse(BaseModel):
    total: int
    items: list[NewsItem]
    sources: list[dict] = []


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    database: str
    news_count: int


class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="用户问题")
    top_k: int = Field(default=5, ge=1, le=20, description="检索条数")


class Citation(BaseModel):
    news_id: int
    title: str
    link: str


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    # 公开演示的配额提示：前端用来展示「今日剩余 N 次」
    remaining_quota: int | None = None


class StatsResponse(BaseModel):
    total_news: int
    ai_analyzed: int
    total_traces: int
    total_cost_yuan: float
    total_input_tokens: int
    total_output_tokens: int
    # Day 25 扩展：让看板能回答「钱花在哪个链路」「最近每天花多少」
    error_traces: int = 0
    avg_cost_per_call_yuan: float = 0.0
    window_days: int = 0          # 0 = 全量
    by_purpose: list[dict] = []
    daily: list[dict] = []
    cost_note: str = ""
    ask_quota: dict = {}          # 公开问答配额使用情况（不含 IP）


class TriggerResponse(BaseModel):
    status: str
    message: str
    candidates: int = 0


class ReviewItem(BaseModel):
    id: int
    news_id: int
    review_type: str
    original_value: Optional[str] = None
    suggested_value: Optional[str] = None
    reason: Optional[str] = None
    status: str
    reviewer_note: Optional[str] = None
    created_at: str
    reviewed_at: Optional[str] = None


class ReviewListResponse(BaseModel):
    total: int
    items: list[ReviewItem]


class ReviewAction(BaseModel):
    action: str = Field(..., description="approve 或 reject")
    note: str = Field(default="", description="审核备注")
