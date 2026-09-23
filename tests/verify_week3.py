# -*- coding: utf-8 -*-
"""Week 3 联合验收（Day 21）：三条链路一次性全部跑通

链路 A：分类/分析 —— analyze.py 对未分析新闻做分类 + 摘要（LLM）
链路 B：RAG 问答 —— api /ask 端点（fastapi TestClient，不起服务器）
链路 C：Agent   —— agent/graph.py 完整情报任务（LangGraph 6 节点）

用法：
  .venv/Scripts/python.exe tests/verify_week3.py
输出：data/week3_acceptance.json
"""
import json
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BASE_DIR, ".env"))

RESULTS_PATH = os.path.join(BASE_DIR, "data", "week3_acceptance.json")
VENV_PY = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")


def chain_analyze() -> dict:
    """链路 A：分类/分析（真实调用 analyze.py，限 3 条控制成本）"""
    t0 = time.time()
    p = subprocess.run(
        [VENV_PY, os.path.join(BASE_DIR, "analyze.py"), "--limit", "3"],
        capture_output=True, text=True, timeout=600,
    )
    ok = p.returncode == 0
    return {
        "ok": ok,
        "elapsed_s": round(time.time() - t0, 1),
        "tail": (p.stdout or p.stderr)[-400:],
    }


def chain_rag() -> dict:
    """链路 B：RAG 问答（/ask 端点，TestClient 直调 FastAPI app）"""
    t0 = time.time()
    from fastapi.testclient import TestClient

    from api.main import app

    with TestClient(app) as client:
        r = client.post("/ask", json={"query": "OpenAI 最近在数学领域有什么新动作？", "top_k": 5})
        ok = r.status_code == 200 and len(r.json().get("answer", "")) > 20
        body = r.json()
        citations = body.get("citations") or []
    return {
        "ok": ok,
        "elapsed_s": round(time.time() - t0, 1),
        "answer_head": body.get("answer", "")[:120],
        "citations": len(citations),
    }


def chain_agent() -> dict:
    """链路 C：Agent 完整情报任务（LangGraph 状态图端到端）"""
    t0 = time.time()
    from agent.graph import run_agent

    result = run_agent("总结今日 AI 领域重要进展，重点覆盖大模型与产品动态")
    report = result.get("report") or ""
    ok = result.get("status") in ("published", "completed") and len(report) > 200
    return {
        "ok": ok,
        "elapsed_s": round(time.time() - t0, 1),
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "report_len": len(report),
    }


def main():
    results = {}
    print("=== 链路 A：分类/分析 ===")
    results["analyze"] = chain_analyze()
    print("ok" if results["analyze"]["ok"] else "FAIL", results["analyze"]["elapsed_s"], "s")

    print("=== 链路 B：RAG 问答 ===")
    results["rag"] = chain_rag()
    print("ok" if results["rag"]["ok"] else "FAIL", results["rag"]["elapsed_s"], "s",
          "引用", results["rag"]["citations"])

    print("=== 链路 C：Agent ===")
    results["agent"] = chain_agent()
    print("ok" if results["agent"]["ok"] else "FAIL", results["agent"]["elapsed_s"], "s",
          "报告", results["agent"]["report_len"], "字")

    results["all_pass"] = all(results[k]["ok"] for k in ("analyze", "rag", "agent"))
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n=== 结论 ===")
    print("三条链路全部成功" if results["all_pass"] else "存在失败链路，见 data/week3_acceptance.json")


if __name__ == "__main__":
    main()
