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


class StatsResponse(BaseModel):
    total_news: int
    ai_analyzed: int
    total_traces: int
    total_cost_yuan: float
    total_input_tokens: int
    total_output_tokens: int


class TriggerResponse(BaseModel):
    status: str
    message: str
    candidates: int = 0
