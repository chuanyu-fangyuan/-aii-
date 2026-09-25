"""Agent 工具层

5 个 LangChain 工具，复用已有模块：
  - search_news: 语义检索新闻
  - fetch_source: 按来源获取新闻
  - dedup_check: URL 去重检查
  - verify_claim: 事实核查
  - write_report: 生成报告
"""

import json
import os
import sqlite3
import sys
from typing import List, Optional

from langchain_core.tools import tool

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

SQLITE_PATH = os.path.join(BASE_DIR, "data", "news.db")


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@tool
def search_news(query: str, top_k: int = 5) -> str:
    """搜索新闻数据库，返回与查询最相关的新闻列表。

    Args:
        query: 搜索关键词或问题
        top_k: 返回结果数量，默认 5

    Returns:
        JSON 格式的新闻列表，包含标题、来源、摘要、分类等
    """
    from retrieval import search

    results = search(query, top_k=top_k)
    if not results:
        return json.dumps({"error": "未找到相关新闻", "count": 0}, ensure_ascii=False)

    items = []
    for r in results:
        items.append({
            "id": r.news_id,
            "title": r.title,
            "url": r.url,
            "source": r.source_name,
            "category": r.ai_category,
            "summary": r.ai_summary_zh or "",
            "score": round(r.score, 4),
        })

    return json.dumps({"count": len(items), "results": items}, ensure_ascii=False)


@tool
def fetch_source(source_id: str, days: int = 7, limit: int = 20) -> str:
    """按来源获取最近新闻。

    Args:
        source_id: 来源 ID（hackernews / techcrunch / theverge / arxiv）
        days: 时间范围（天），默认 7
        limit: 返回条数上限，默认 20

    Returns:
        JSON 格式的新闻列表
    """
    valid_sources = {"hackernews", "techcrunch", "theverge", "arxiv"}
    if source_id not in valid_sources:
        return json.dumps(
            {"error": f"无效来源: {source_id}，可选: {list(valid_sources)}"},
            ensure_ascii=False,
        )

    conn = _get_db()
    rows = conn.execute(
        """SELECT id, title, url, source_name, ai_category, ai_summary_zh, published_at
           FROM news
           WHERE source_id = ?
             AND COALESCE(published_at, fetched_at) >= datetime('now', ? || ' days')
           ORDER BY COALESCE(published_at, fetched_at) DESC
           LIMIT ?""",
        (source_id, f"-{days}", limit),
    ).fetchall()
    conn.close()

    if not rows:
        return json.dumps({"source": source_id, "count": 0, "results": []}, ensure_ascii=False)

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "title": r["title"],
            "url": r["url"],
            "category": r["ai_category"],
            "summary": r["ai_summary_zh"] or "",
            "published": r["published_at"],
        })

    return json.dumps({"source": source_id, "count": len(items), "results": items}, ensure_ascii=False)


@tool
def dedup_check(url: str) -> str:
    """检查 URL 是否已存在于数据库中。

    Args:
        url: 待检查的 URL

    Returns:
        JSON 格式，包含 exists 字段和匹配的新闻 ID（如存在）
    """
    from fetch import canonical_url

    normalized = canonical_url(url)
    conn = _get_db()

    # 精确匹配
    row = conn.execute(
        "SELECT id, title, url FROM news WHERE url = ? OR url_hash = ?",
        (url, normalized),
    ).fetchone()

    if row:
        conn.close()
        return json.dumps({
            "exists": True,
            "news_id": row["id"],
            "title": row["title"],
            "url": row["url"],
        }, ensure_ascii=False)

    # 模糊匹配（标题相似度）
    from fetch import title_hash

    h = title_hash(url)  # 复用标题哈希逻辑
    similar = conn.execute(
        "SELECT id, title FROM news WHERE title_hash = ? LIMIT 3",
        (h,),
    ).fetchall()

    conn.close()

    if similar:
        matches = [{"id": r["id"], "title": r["title"]} for r in similar]
        return json.dumps({
            "exists": False,
            "similar_matches": matches,
            "note": "标题哈希相似，可能重复",
        }, ensure_ascii=False)

    return json.dumps({"exists": False, "note": "数据库中不存在该 URL"}, ensure_ascii=False)


@tool
def verify_claim(claim: str, news_ids: Optional[List[int]] = None) -> str:
    """核查声明的真实性，基于数据库中的新闻或外部知识。

    Args:
        claim: 待核查的声明
        news_ids: 可选，参考的新闻 ID 列表

    Returns:
        JSON 格式，包含验证结果、置信度和依据
    """
    # 获取参考新闻
    context_parts = []
    if news_ids:
        conn = _get_db()
        placeholders = ",".join("?" * len(news_ids))
        rows = conn.execute(
            f"SELECT id, title, ai_summary_zh, source_name FROM news WHERE id IN ({placeholders})",
            news_ids,
        ).fetchall()
        conn.close()

        for i, r in enumerate(rows, 1):
            summary = r["ai_summary_zh"] or "(无摘要)"
            context_parts.append(f"[{i}] {r['title']} ({r['source_name']}): {summary}")

    context = "\n".join(context_parts) if context_parts else "无特定参考新闻"

    # 调用 DeepSeek 进行核查
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE_DIR, ".env"))
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    if not api_key:
        return json.dumps({"error": "API Key 未配置"}, ensure_ascii=False)

    prompt = f"""请核查以下声明的真实性。基于提供的新闻上下文（如有）和你的知识进行判断。

声明：{claim}

参考新闻：
{context}

请按以下 JSON 格式返回结果（不要添加其他内容）：
{{
  "verdict": "confirmed" | "unverified" | "disputed",
  "confidence": 0.0-1.0,
  "reasoning": "核查理由",
  "sources": ["相关来源说明"]
}}"""

    # 走统一入口：Agent 的每次核查也要计入成本（purpose='agent_verify'）
    from llm import chat

    out = chat(
        [{"role": "user", "content": prompt}],
        purpose="agent_verify",
        temperature=0.1,
        max_tokens=500,
        timeout=30,
        api_key=api_key,
    )
    if not out["ok"]:
        return json.dumps({"error": f"核查失败: {out['error_message']}"}, ensure_ascii=False)

    try:
        result = json.loads(out["content"])
        return json.dumps(result, ensure_ascii=False)
    except json.JSONDecodeError:
        return json.dumps({"raw_response": out["content"]}, ensure_ascii=False)


@tool
def write_report(topics: str, max_words: int = 800) -> str:
    """基于新闻数据库生成主题报告。

    Args:
        topics: 报告主题，多个主题用逗号分隔
        max_words: 最大字数，默认 800

    Returns:
        JSON 格式，包含报告内容和引用的新闻 ID
    """
    # 搜索相关新闻
    topic_list = [t.strip() for t in topics.split(",") if t.strip()]
    all_results = []
    for topic in topic_list:
        from retrieval import search
        results = search(topic, top_k=5)
        all_results.extend(results)

    # 去重
    seen_ids = set()
    unique_results = []
    for r in all_results:
        if r.news_id not in seen_ids:
            seen_ids.add(r.news_id)
            unique_results.append(r)

    if not unique_results:
        return json.dumps({"error": "未找到相关新闻，无法生成报告"}, ensure_ascii=False)

    # 构建上下文
    context_parts = []
    for i, r in enumerate(unique_results[:15], 1):  # 最多 15 条
        summary = r.ai_summary_zh or "(无摘要)"
        cat = f"[{r.ai_category}]" if r.ai_category else ""
        context_parts.append(f"[{i}] {cat} {r.title}\n    来源: {r.source_name}\n    {summary}")

    context = "\n\n".join(context_parts)

    # 调用 DeepSeek 生成报告
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE_DIR, ".env"))
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    if not api_key:
        return json.dumps({"error": "API Key 未配置"}, ensure_ascii=False)

    prompt = f"""请基于以下新闻资料，生成一份关于「{topics}」的简报。

要求：
- 字数控制在 {max_words} 字以内
- 结构清晰，包含要点总结
- 引用新闻时用 [序号] 标注

新闻资料：
{context}

请直接输出报告内容，不要添加 JSON 格式。"""

    # 走统一入口：报告生成本身是 Agent 链路里最贵的一次调用，必须计入（purpose='agent_report'）
    from llm import chat

    out = chat(
        [{"role": "user", "content": prompt}],
        purpose="agent_report",
        temperature=0.3,
        max_tokens=1500,
        timeout=60,
        api_key=api_key,
    )
    if not out["ok"]:
        return json.dumps({"error": f"报告生成失败: {out['error_message']}"}, ensure_ascii=False)

    return json.dumps({
        "topics": topics,
        "report": out["content"],
        "cited_news_ids": list(seen_ids)[:10],  # 引用的新闻 ID
        "news_count": len(unique_results),
    }, ensure_ascii=False)


# 工具列表（供 Agent 使用）
ALL_TOOLS = [search_news, fetch_source, dedup_check, verify_claim, write_report]
