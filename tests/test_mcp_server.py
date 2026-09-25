"""MCP Server 工具清单测试

只校验「对外暴露了哪 5 个工具、schema 是否可解析」——不实际调用 LLM 工具，
那部分由 tests/verify_mcp.py 做人工可复现的验收。
"""

import asyncio
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from fastmcp import Client  # noqa: E402
from mcp_server.server import mcp  # noqa: E402


EXPECTED_TOOLS = {"search_news", "fetch_source", "dedup_check", "verify_claim", "write_report"}


def list_tools():
    async def _inner():
        async with Client(mcp) as client:
            return await client.list_tools()

    return asyncio.run(_inner())


def test_exposes_exactly_five_tools():
    assert {t.name for t in list_tools()} == EXPECTED_TOOLS


def test_every_tool_has_description_and_schema():
    """MCP 工具是给模型看的，缺描述或缺参数 schema 等于不可用"""
    for tool in list_tools():
        assert tool.description, f"{tool.name} 缺少描述"
        assert tool.inputSchema is not None, f"{tool.name} 缺少参数 schema"
        assert tool.inputSchema.get("type") == "object"


def test_search_tools_accept_query():
    schema = {t.name: t.inputSchema for t in list_tools()}
    assert "query" in schema["search_news"]["properties"]
    assert "source_id" in schema["fetch_source"]["properties"]
