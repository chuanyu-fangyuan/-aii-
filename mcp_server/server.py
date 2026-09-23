"""MCP Server - 暴露 AI 情报站工具

使用 FastMCP 将 5 个工具暴露为 MCP 服务，
可被 Claude Desktop / Cursor 等客户端调用。

启动：
  python -m mcp_server.server

或使用 uvicorn:
  uvicorn mcp_server.server:app
"""

import json
import os
import sys

# 确保项目根目录在 path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from fastmcp import FastMCP

# 创建 MCP 服务器
mcp = FastMCP("AI 情报站")


@mcp.tool()
def search_news(query: str, top_k: int = 5) -> str:
    """搜索新闻数据库，返回与查询最相关的新闻列表。

    Args:
        query: 搜索关键词或问题
        top_k: 返回结果数量，默认 5

    Returns:
        JSON 格式的新闻列表
    """
    from agent.tools import search_news as _search

    return _search.invoke({"query": query, "top_k": top_k})


@mcp.tool()
def fetch_source(source_id: str, days: int = 7, limit: int = 20) -> str:
    """按来源获取最近新闻。

    Args:
        source_id: 来源 ID（hackernews / techcrunch / theverge / arxiv）
        days: 时间范围（天），默认 7
        limit: 返回条数上限，默认 20

    Returns:
        JSON 格式的新闻列表
    """
    from agent.tools import fetch_source as _fetch

    return _fetch.invoke({"source_id": source_id, "days": days, "limit": limit})


@mcp.tool()
def dedup_check(url: str) -> str:
    """检查 URL 是否已存在于数据库中。

    Args:
        url: 待检查的 URL

    Returns:
        JSON 格式，包含 exists 字段
    """
    from agent.tools import dedup_check as _dedup

    return _dedup.invoke({"url": url})


@mcp.tool()
def verify_claim(claim: str, news_ids: list = None) -> str:
    """核查声明的真实性。

    Args:
        claim: 待核查的声明
        news_ids: 可选，参考的新闻 ID 列表

    Returns:
        JSON 格式，包含验证结果
    """
    from agent.tools import verify_claim as _verify

    return _verify.invoke({"claim": claim, "news_ids": news_ids or []})


@mcp.tool()
def write_report(topics: str, max_words: int = 800) -> str:
    """基于新闻数据库生成主题报告。

    Args:
        topics: 报告主题，多个主题用逗号分隔
        max_words: 最大字数，默认 800

    Returns:
        JSON 格式，包含报告内容
    """
    from agent.tools import write_report as _write

    return _write.invoke({"topics": topics, "max_words": max_words})


# 启动入口
if __name__ == "__main__":
    import uvicorn

    # FastMCP 服务器默认使用 SSE 传输
    mcp.run(transport="sse")
