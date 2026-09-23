# -*- coding: utf-8 -*-
"""RAG 评测 v2：RAGAS 口径三指标 + LLM-as-judge（Day 20）

说明（如实披露）：
  ragas 官方库 0.2.x/0.4.x 均硬依赖 langchain_community.chat_models.vertexai，
  与本项目 Agent 所需的 langchain 1.x 生态互斥（详见 report_week3.md）。
  为保住 Agent 运行环境，本脚本按 RAGAS 论文口径用 DeepSeek 自实现三项指标：
    - faithfulness      判断把答案拆成原子断言后，被上下文支持的断言占比
    - answer_relevancy  答案对问题的针对性与完整度（1-5 归一到 0-1）
    - context_precision 相关资料是否排在检索结果前部（precision@rank 均值）
  另含 LLM-as-judge rubric 总分（1-5）与 v1/v2 Prompt 对比实验。

用法：
  .venv/Scripts/python.exe evals/eval_rag.py [--limit 20] [--prompt v1|v2|both]
"""
import argparse
import json
import os
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BASE_DIR, ".env"))

import requests  # noqa: E402

from retrieval import search  # noqa: E402

API_URL = "https://api.deepseek.com/chat/completions"
QA_PATH = os.path.join(BASE_DIR, "evals", "rag_qa.jsonl")
RESULTS_PATH = os.path.join(BASE_DIR, "evals", "rag_eval_results.jsonl")
COST_LOG = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def llm(prompt: str, temperature: float = 0.2, max_tokens: int = 900) -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    assert api_key, "DEEPSEEK_API_KEY 未配置"
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json={"model": "deepseek-chat",
              "messages": [{"role": "user", "content": prompt}],
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    COST_LOG["calls"] += 1
    COST_LOG["prompt_tokens"] += usage.get("prompt_tokens", 0)
    COST_LOG["completion_tokens"] += usage.get("completion_tokens", 0)
    return data["choices"][0]["message"]["content"]


def build_context(results) -> str:
    parts = []
    for i, r in enumerate(results, 1):
        summary = getattr(r, "ai_summary_zh", None) or "(无摘要)"
        parts.append(f"[{i}] {r.title}\n    来源: {r.source_name}\n    {summary}")
    return "\n\n".join(parts)


def extract_json(text: str):
    m = re.search(r"\{.*\}|\[.*\]", text, re.S)
    if not m:
        raise ValueError(f"judge 输出无 JSON: {text[:120]}")
    return json.loads(m.group(0))


# ------------------------------------------------ 生成答案（与 /ask 同构）

def answer_question(query: str, prompt_version: str, top_k: int = 5):
    results = search(query, top_k=top_k)
    context = build_context(results)
    template = open(os.path.join(BASE_DIR, "prompts", f"rag_{prompt_version}.txt"),
                    encoding="utf-8").read()
    prompt = template.replace("{context}", context).replace("{query}", query)
    answer = llm(prompt, temperature=0.3)
    return answer, results, context


# ------------------------------------------------ 三指标 + judge（一次调用完成）

JUDGE_PROMPT = """你是一个严格的 RAG 评测裁判。给定【问题】【标准参考答案】【检索资料】【模型答案】，请输出 JSON（只输出 JSON，不要多余文字）：

{{
  "claims": [{{"text": "从模型答案中拆出的一条原子断言", "supported": true/false}}],
  "answer_relevancy": 1-5 的整数，模型答案对问题的针对性与完整度（5=完全切题且完整）,
  "context_relevance": [检索资料1到{top_k}的相关性，1 或 0，1=与问题相关，0=无关],
  "rubric": 1-5 的整数，综合评分：有用性、引用规范、无编造（5=优秀）
}}

判定标准：
- supported=true 当且仅当该断言能从检索资料直接推出；模型答案合理的引用标注可作为佐证
- 声明资料不足/无法回答不算错误，编造才算错误
- context_relevance 按资料顺序给出 {top_k} 个值

【问题】{query}
【标准参考答案】{ground_truth}
【检索资料】{context}
【模型答案】{answer}
"""


def evaluate_answer(query, ground_truth, context, answer, top_k):
    raw = llm(JUDGE_PROMPT.format(query=query, ground_truth=ground_truth,
                                  context=context, answer=answer, top_k=top_k),
              temperature=0.0)
    j = extract_json(raw)

    # faithfulness = supported claims / total claims（无断言记 1.0，答案为空记 0）
    claims = j.get("claims", [])
    if not claims:
        faithfulness = 0.0 if len(answer.strip()) > 20 else 1.0
    else:
        faithfulness = sum(1 for c in claims if c.get("supported")) / len(claims)

    # answer_relevancy 1-5 -> 0-1
    relevancy = max(1, min(5, int(j.get("answer_relevancy", 1)))) / 5

    # context_precision：RAGAS 口径 = 相关资料处的 precision@rank 均值
    rel = [1 if x else 0 for x in j.get("context_relevance", [])][:top_k]
    while len(rel) < top_k:
        rel.append(0)
    hits = 0
    precisions = []
    for rank, is_rel in enumerate(rel, 1):
        if is_rel:
            hits += 1
            precisions.append(hits / rank)
    context_precision = sum(precisions) / len(precisions) if precisions else 0.0

    rubric = max(1, min(5, int(j.get("rubric", 1))))

    return {
        "faithfulness": round(faithfulness, 4),
        "answer_relevancy": round(relevancy, 4),
        "context_precision": round(context_precision, 4),
        "rubric": rubric,
    }


# ------------------------------------------------ 主流程

def run(prompt_versions, limit):
    qas = [json.loads(l) for l in open(QA_PATH, encoding="utf-8") if l.strip()][:limit]
    all_rows = []
    for pv in prompt_versions:
        print(f"\n===== Prompt {pv} × {len(qas)} 题 =====")
        for qa in qas:
            t0 = time.time()
            answer, results, context = answer_question(qa["query"], pv)
            scores = evaluate_answer(qa["query"], qa["ground_truth"],
                                     context, answer, top_k=5)
            row = {"prompt": pv, **qa, "answer": answer, **scores,
                   "elapsed_s": round(time.time() - t0, 1),
                   "cited_ids": [r.news_id for r in results]}
            all_rows.append(row)
            print(f"  [{qa['id']:2d}] f={scores['faithfulness']:.2f} "
                  f"ar={scores['answer_relevancy']:.2f} "
                  f"cp={scores['context_precision']:.2f} rubric={scores['rubric']} "
                  f"({row['elapsed_s']}s)")

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 汇总
    summary = {}
    for pv in prompt_versions:
        rows = [r for r in all_rows if r["prompt"] == pv]
        summary[pv] = {k: round(sum(r[k] for r in rows) / len(rows), 4)
                       for k in ("faithfulness", "answer_relevancy",
                                 "context_precision", "rubric")}
    print("\n===== 汇总（0-1，rubric 为 1-5）=====")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("成本:", COST_LOG)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--prompt", default="both", help="v1 | v2 | both")
    args = ap.parse_args()
    versions = ["v1", "v2"] if args.prompt == "both" else [args.prompt]
    run(versions, args.limit)
