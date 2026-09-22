#!/usr/bin/env python3
"""检索评测

评测指标：Recall@5 / MRR / NDCG@5
使用人工标注的检索测试集（evals/retrieval_queries.jsonl）。

每条测试数据格式：
{"query": "...", "relevant_ids": [123, 456, ...]}

用法：
  python evals/eval_retrieval.py
  python evals/eval_retrieval.py --json
"""

import argparse
import json
import math
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

DEFAULT_QUERIES = os.path.join(BASE_DIR, "evals", "retrieval_queries.jsonl")


def load_queries(path: str) -> list:
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def evaluate(queries: list, top_k: int = 5) -> dict:
    from retrieval import search

    if not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

    results_per_query = []

    for entry in queries:
        query = entry["query"]
        relevant_ids = set(entry["relevant_ids"])

        search_results = search(query, top_k=top_k)
        retrieved_ids = [r.news_id for r in search_results]

        hits = sum(1 for rid in retrieved_ids if rid in relevant_ids)
        recall = hits / len(relevant_ids) if relevant_ids else 0

        rr = 0
        for i, rid in enumerate(retrieved_ids):
            if rid in relevant_ids:
                rr = 1.0 / (i + 1)
                break

        dcg = 0
        for i, rid in enumerate(retrieved_ids):
            if rid in relevant_ids:
                dcg += 1.0 / math.log2(i + 2)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant_ids), top_k)))
        ndcg = dcg / idcg if idcg > 0 else 0

        results_per_query.append({
            "query": query,
            "recall@k": round(recall, 4),
            "rr": round(rr, 4),
            "ndcg@k": round(ndcg, 4),
            "retrieved": retrieved_ids,
            "relevant": list(relevant_ids),
        })

    avg_recall = sum(r["recall@k"] for r in results_per_query) / len(results_per_query)
    avg_mrr = sum(r["rr"] for r in results_per_query) / len(results_per_query)
    avg_ndcg = sum(r["ndcg@k"] for r in results_per_query) / len(results_per_query)

    return {
        "total_queries": len(queries),
        "top_k": top_k,
        "recall@k": round(avg_recall, 4),
        "mrr": round(avg_mrr, 4),
        "ndcg@k": round(avg_ndcg, 4),
        "per_query": results_per_query,
    }


def print_report(metrics: dict):
    print("=" * 60)
    print("检索评测报告")
    print("=" * 60)
    print(f"测试 query 数: {metrics['total_queries']}")
    print(f"top_k: {metrics['top_k']}")
    print()
    print(f"Recall@{metrics['top_k']}:  {metrics['recall@k']:.4f}")
    print(f"MRR:         {metrics['mrr']:.4f}")
    print(f"NDCG@{metrics['top_k']}:  {metrics['ndcg@k']:.4f}")
    print()

    print("逐 query 明细:")
    print("-" * 60)
    for r in metrics["per_query"]:
        print(f"  Q: {r['query'][:40]}")
        print(f"    Recall={r['recall@k']:.2f}  MRR={r['rr']:.2f}  NDCG={r['ndcg@k']:.2f}")
    print("-" * 60)
    print()

    recall_threshold = 0.65
    print(f"Week 2 验收标准 (Recall@{metrics['top_k']} >= {recall_threshold}):")
    if metrics["recall@k"] >= recall_threshold:
        print(f"  ✓ PASS: Recall@{metrics['top_k']} = {metrics['recall@k']:.4f} >= {recall_threshold}")
    else:
        print(f"  ✗ FAIL: Recall@{metrics['top_k']} = {metrics['recall@k']:.4f} < {recall_threshold}")


def main():
    ap = argparse.ArgumentParser(description="检索评测")
    ap.add_argument("--input", default=DEFAULT_QUERIES, help="检索测试集路径")
    ap.add_argument("--top-k", type=int, default=5, help="top-k 检索数")
    ap.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"[error] 测试集不存在: {args.input}")
        print("[info] 请创建 evals/retrieval_queries.jsonl")
        sys.exit(1)

    queries = load_queries(args.input)
    if not queries:
        print("[error] 测试集为空")
        sys.exit(1)

    metrics = evaluate(queries, top_k=args.top_k)

    if args.json:
        output = {k: v for k, v in metrics.items() if k != "per_query"}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_report(metrics)


if __name__ == "__main__":
    main()
