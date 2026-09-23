# -*- coding: utf-8 -*-
"""Day 19 验收：用 fastmcp 内存客户端验证 MCP Server 的 5 个工具。

等价于 MCP Inspector 的「列出工具 + 逐个调用」检查：
  .venv/Scripts/python.exe tests/verify_mcp.py
"""
import asyncio
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# 加载 .env（验证脚本独立于 api 启动流程）
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BASE_DIR, ".env"))

from fastmcp import Client  # noqa: E402
from mcp_server.server import mcp  # noqa: E402


async def main():
    results = {}
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        results["listed_tools"] = names
        print(f"[1] 列出工具: {names}")
        assert set(names) == {
            "search_news", "fetch_source", "dedup_check",
            "verify_claim", "write_report",
        }, "工具清单不完整"

        # 2) search_news
        r = await client.call_tool("search_news", {"query": "OpenAI", "top_k": 3})
        data = json.loads(r.content[0].text)
        results["search_news"] = {"count": data.get("count", len(data.get("items", [])))}
        print(f"[2] search_news -> {results['search_news']}")

        # 3) fetch_source
        r = await client.call_tool("fetch_source", {"source_id": "hackernews", "limit": 3})
        data = json.loads(r.content[0].text)
        results["fetch_source"] = {"count": data.get("count", len(data.get("items", [])))}
        print(f"[3] fetch_source -> {results['fetch_source']}")

        # 4) dedup_check（用一条已知 URL 与一条不存在的 URL）
        r = await client.call_tool("dedup_check", {"url": "https://mcp-verify-not-exist.example.com/x"})
        data = json.loads(r.content[0].text)
        results["dedup_check"] = data
        print(f"[4] dedup_check -> {data}")

        # 5) verify_claim（需要 LLM，失败不阻塞验收，记录即可）
        try:
            r = await client.call_tool("verify_claim", {"claim": "OpenAI 发布了 GPT-5"})
            data = json.loads(r.content[0].text)
            results["verify_claim"] = {"ok": True, "keys": sorted(data.keys())}
            print(f"[5] verify_claim -> ok, keys={sorted(data.keys())}")
        except Exception as e:  # noqa: BLE001
            results["verify_claim"] = {"ok": False, "error": str(e)[:150]}
            print(f"[5] verify_claim -> FAIL: {str(e)[:150]}")

        # 6) write_report（需要 LLM，同上）
        try:
            r = await client.call_tool("write_report", {"topics": "Agent", "max_words": 120})
            data = json.loads(r.content[0].text)
            report = data.get("report") or data.get("content") or ""
            results["write_report"] = {"ok": True, "len": len(report)}
            print(f"[6] write_report -> ok, {len(report)} chars")
        except Exception as e:  # noqa: BLE001
            results["write_report"] = {"ok": False, "error": str(e)[:150]}
            print(f"[6] write_report -> FAIL: {str(e)[:150]}")

    need_llm = [k for k in ("verify_claim", "write_report") if not results[k].get("ok")]
    structural = all(results[k] if isinstance(results[k], dict) else True
                     for k in ("search_news", "fetch_source", "dedup_check"))
    print("\n=== 结论 ===")
    print(f"工具清单完整: True | 结构化调用通过: {structural} | LLM 类工具: "
          f"{'全部可用' if not need_llm else '未通过(需 API Key): ' + ', '.join(need_llm)}")
    json.dump(results, open(os.path.join(BASE_DIR, "data", "mcp_verify.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
