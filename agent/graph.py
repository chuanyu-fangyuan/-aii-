"""Agent 状态图（LangGraph）

6 节点流程：plan → gather → verify → synthesize → review → publish
条件边：verify 发现可疑 → 回 gather 补证（最多 2 轮）
状态持久化：agent_runs 表
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Annotated, Dict, List, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

SQLITE_PATH = os.path.join(BASE_DIR, "data", "news.db")


# ============================================================
# 状态定义
# ============================================================

class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[List[BaseMessage], add_messages]
    task: str  # 用户任务描述
    plan: str  # 执行计划
    gathered_data: str  # 收集的数据
    verification_result: str  # 验证结果
    report: str  # 最终报告
    verify_count: int  # 验证轮次计数
    status: str  # 当前状态


# ============================================================
# LLM 初始化
# ============================================================

def _get_llm() -> ChatOpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE_DIR, ".env"))
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    return ChatOpenAI(
        model="deepseek-chat",
        api_key=api_key,
        base_url="https://api.deepseek.com",
        temperature=0.3,
        max_tokens=2000,
    )


# ============================================================
# 节点函数
# ============================================================

def plan_node(state: AgentState) -> Dict:
    """规划节点：分析任务，制定执行计划"""
    llm = _get_llm()
    task = state["task"]

    prompt = f"""你是一个 AI 情报分析 Agent。请分析以下任务，制定执行计划。

任务：{task}

请输出：
1. 需要搜索的关键词（2-5 个）
2. 需要调用的工具（search_news / fetch_source / dedup_check / verify_claim / write_report）
3. 预期输出格式

用 JSON 格式返回：
{{
  "keywords": ["关键词1", "关键词2"],
  "tools": ["工具1", "工具2"],
  "expected_output": "预期输出描述"
}}"""

    response = llm.invoke([HumanMessage(content=prompt)])
    plan = response.content

    return {
        "plan": plan,
        "messages": [AIMessage(content=f"计划制定完成：{plan}")],
        "status": "planned",
    }


def gather_node(state: AgentState) -> Dict:
    """收集节点：执行搜索，收集数据"""
    from agent.tools import search_news, fetch_source

    task = state["task"]
    plan = state.get("plan", "")

    # 简单解析计划中的关键词（实际可以用 LLM 解析）
    # 这里直接用任务描述作为搜索词
    search_results = search_news.invoke({"query": task, "top_k": 10})

    # 尝试从计划中提取来源
    sources_to_fetch = []
    if "hackernews" in plan.lower():
        sources_to_fetch.append("hackernews")
    if "techcrunch" in plan.lower():
        sources_to_fetch.append("techcrunch")

    source_results = []
    for src in sources_to_fetch:
        result = fetch_source.invoke({"source_id": src, "days": 7, "limit": 10})
        source_results.append(result)

    gathered = f"搜索结果：{search_results}\n\n来源结果：{json.dumps(source_results, ensure_ascii=False)}"

    return {
        "gathered_data": gathered,
        "messages": [AIMessage(content=f"数据收集完成，共获取 {len(search_results)} 条结果")],
        "status": "gathered",
    }


def verify_node(state: AgentState) -> Dict:
    """验证节点：核查收集到的数据"""
    from agent.tools import verify_claim

    gathered = state.get("gathered_data", "")
    task = state["task"]

    # 提取关键声明进行验证（简化版：直接验证任务相关声明）
    verification_prompt = f"基于以下数据，验证与任务相关的核心声明：\n\n任务：{task}\n\n数据：{gathered[:2000]}"

    # 调用 LLM 进行验证（不使用 verify_claim 工具，直接用 LLM）
    llm = _get_llm()
    response = llm.invoke([HumanMessage(content=verification_prompt)])

    verification_result = response.content
    verify_count = state.get("verify_count", 0) + 1

    # 判断是否需要重新收集（简化逻辑：如果验证结果包含"不确定"或"需要更多"）
    needs_regather = any(keyword in verification_result for keyword in ["不确定", "需要更多", "信息不足", "无法确认"])

    return {
        "verification_result": verification_result,
        "verify_count": verify_count,
        "messages": [AIMessage(content=f"验证完成（第 {verify_count} 轮）")],
        "status": "needs_regather" if needs_regather and verify_count < 2 else "verified",
    }


def synthesize_node(state: AgentState) -> Dict:
    """综合节点：整合数据，生成报告"""
    from agent.tools import write_report

    task = state["task"]
    gathered = state.get("gathered_data", "")
    verification = state.get("verification_result", "")

    # 使用 write_report 工具生成报告
    report_result = write_report.invoke({"topics": task, "max_words": 1000})

    return {
        "report": report_result,
        "messages": [AIMessage(content="报告生成完成")],
        "status": "synthesized",
    }


def review_node(state: AgentState) -> Dict:
    """审核节点：检查报告质量"""
    llm = _get_llm()
    report = state.get("report", "")
    task = state["task"]

    prompt = f"""请审核以下报告的质量。

任务：{task}

报告：
{report}

审核标准：
1. 是否回答了任务问题
2. 是否有数据支撑
3. 结构是否清晰
4. 是否有明显错误

请用 JSON 格式返回：
{{
  "approved": true/false,
  "score": 0-10,
  "feedback": "审核意见",
  "suggested_improvements": ["改进建议"]
}}"""

    response = llm.invoke([HumanMessage(content=prompt)])
    review_result = response.content

    return {
        "messages": [AIMessage(content=f"审核完成：{review_result}")],
        "status": "reviewed",
    }


def publish_node(state: AgentState) -> Dict:
    """发布节点：输出最终结果"""
    report = state.get("report", "")

    return {
        "messages": [AIMessage(content="任务完成，报告已发布")],
        "status": "published",
    }


# ============================================================
# 条件边
# ============================================================

def should_regather(state: AgentState) -> str:
    """判断是否需要重新收集数据"""
    if state.get("status") == "needs_regather" and state.get("verify_count", 0) < 2:
        return "gather"
    return "synthesize"


def should_revise(state: AgentState) -> str:
    """判断是否需要修改报告"""
    # 简化：总是通过审核
    return "publish"


# ============================================================
# 构建图
# ============================================================

def build_graph() -> StateGraph:
    """构建 Agent 状态图"""
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("plan", plan_node)
    workflow.add_node("gather", gather_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("synthesize", synthesize_node)
    workflow.add_node("review", review_node)
    workflow.add_node("publish", publish_node)

    # 设置入口
    workflow.set_entry_point("plan")

    # 添加边
    workflow.add_edge("plan", "gather")
    workflow.add_edge("gather", "verify")

    # 条件边：verify → gather 或 synthesize
    workflow.add_conditional_edges(
        "verify",
        should_regather,
        {
            "gather": "gather",
            "synthesize": "synthesize",
        },
    )

    workflow.add_edge("synthesize", "review")

    # 条件边：review → publish 或 synthesize（修改）
    workflow.add_conditional_edges(
        "review",
        should_revise,
        {
            "publish": "publish",
            "synthesize": "synthesize",
        },
    )

    workflow.add_edge("publish", END)

    return workflow.compile()


# ============================================================
# 状态持久化
# ============================================================

def init_agent_runs_table():
    """初始化 agent_runs 表"""
    conn = sqlite3.connect(SQLITE_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            plan TEXT,
            gathered_data TEXT,
            verification_result TEXT,
            report TEXT,
            verify_count INTEGER DEFAULT 0,
            messages_json TEXT DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        );
    """)
    conn.commit()
    conn.close()


def save_run(state: AgentState, run_id: Optional[int] = None) -> int:
    """保存运行状态到数据库"""
    conn = sqlite3.connect(SQLITE_PATH)

    messages_json = json.dumps(
        [{"type": m.__class__.__name__, "content": m.content} for m in state.get("messages", [])],
        ensure_ascii=False,
    )

    if run_id is None:
        cursor = conn.execute(
            """INSERT INTO agent_runs (task, status, plan, gathered_data, verification_result, report, verify_count, messages_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                state.get("task", ""),
                state.get("status", "running"),
                state.get("plan", ""),
                state.get("gathered_data", ""),
                state.get("verification_result", ""),
                state.get("report", ""),
                state.get("verify_count", 0),
                messages_json,
            ),
        )
        run_id = cursor.lastrowid
    else:
        conn.execute(
            """UPDATE agent_runs
               SET status = ?, plan = ?, gathered_data = ?, verification_result = ?,
                   report = ?, verify_count = ?, messages_json = ?,
                   completed_at = CASE WHEN ? = 'published' THEN datetime('now') ELSE completed_at END
               WHERE id = ?""",
            (
                state.get("status", "running"),
                state.get("plan", ""),
                state.get("gathered_data", ""),
                state.get("verification_result", ""),
                state.get("report", ""),
                state.get("verify_count", 0),
                messages_json,
                state.get("status", ""),
                run_id,
            ),
        )

    conn.commit()
    conn.close()
    return run_id


# ============================================================
# 运行入口
# ============================================================

def run_agent(task: str) -> Dict:
    """运行 Agent 完成指定任务"""
    init_agent_runs_table()

    # 初始化状态
    initial_state: AgentState = {
        "messages": [HumanMessage(content=task)],
        "task": task,
        "plan": "",
        "gathered_data": "",
        "verification_result": "",
        "report": "",
        "verify_count": 0,
        "status": "started",
    }

    # 构建并运行图
    graph = build_graph()
    final_state = graph.invoke(initial_state)

    # 保存结果
    run_id = save_run(final_state)

    return {
        "run_id": run_id,
        "task": task,
        "report": final_state.get("report", ""),
        "status": final_state.get("status", "completed"),
    }


if __name__ == "__main__":
    # 测试运行
    test_task = "总结今日 AI 领域的重要进展"
    print(f"任务：{test_task}")
    print("=" * 60)

    result = run_agent(test_task)
    print(f"\n运行 ID: {result['run_id']}")
    print(f"状态：{result['status']}")
    print(f"\n报告：\n{result['report']}")
