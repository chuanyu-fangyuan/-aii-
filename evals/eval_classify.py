#!/usr/bin/env python3
"""计算分类 F1 分数

读取人工标注的 dataset.jsonl，对比 AI 分类结果，
计算 macro-F1、per-class F1、准确率。

用法：
  python evals/eval_classify.py                      # 使用默认路径
  python evals/eval_classify.py --input evals/dataset.jsonl
"""

import argparse
import json
import os
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATASET = os.path.join(BASE_DIR, "evals", "dataset.jsonl")


def load_dataset(path: str) -> list:
    """加载标注数据集"""
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            # 只取已标注的样本
            if entry.get("expected_category"):
                entries.append(entry)
    return entries


def compute_metrics(entries: list) -> dict:
    """计算分类指标"""
    if not entries:
        return {"error": "没有已标注的样本"}

    # 统计
    tp = defaultdict(int)  # true positive per class
    fp = defaultdict(int)  # false positive per class
    fn = defaultdict(int)  # false negative per class
    correct = 0
    total = len(entries)

    for e in entries:
        pred = e.get("ai_category", "其他") or "其他"
        gold = e.get("expected_category", "其他") or "其他"

        if pred == gold:
            tp[pred] += 1
            correct += 1
        else:
            fp[pred] += 1
            fn[gold] += 1

    # 收集所有出现过的类别
    all_classes = sorted(set(list(tp.keys()) + list(fp.keys()) + list(fn.keys())))

    # 计算 per-class precision, recall, f1
    per_class = {}
    for cls in all_classes:
        precision = tp[cls] / (tp[cls] + fp[cls]) if (tp[cls] + fp[cls]) > 0 else 0.0
        recall = tp[cls] / (tp[cls] + fn[cls]) if (tp[cls] + fn[cls]) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_class[cls] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": tp[cls] + fn[cls],  # 该类的真实样本数
        }

    # Macro F1（各类别 F1 的算术平均）
    macro_f1 = sum(per_class[c]["f1"] for c in all_classes) / len(all_classes) if all_classes else 0.0

    # 准确率
    accuracy = correct / total if total > 0 else 0.0

    return {
        "total_samples": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
    }


def print_report(metrics: dict):
    """打印评测报告"""
    if "error" in metrics:
        print(f"[error] {metrics['error']}")
        return

    print("=" * 60)
    print("AI 分类评测报告")
    print("=" * 60)
    print(f"样本数: {metrics['total_samples']}")
    print(f"准确率: {metrics['accuracy']:.2%}")
    print(f"Macro F1: {metrics['macro_f1']:.4f}")
    print()
    print("分类别指标:")
    print("-" * 60)
    print(f"{'类别':<12} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>8}")
    print("-" * 60)

    for cls, m in sorted(metrics["per_class"].items()):
        print(f"{cls:<12} {m['precision']:>10.4f} {m['recall']:>10.4f} {m['f1']:>10.4f} {m['support']:>8}")

    print("-" * 60)
    print()

    # Week 1 验收标准检查
    print("Week 1 验收标准 (baseline F1 >= 0.60):")
    if metrics["macro_f1"] >= 0.60:
        print(f"  ✓ PASS: Macro F1 = {metrics['macro_f1']:.4f} >= 0.60")
    else:
        print(f"  ✗ FAIL: Macro F1 = {metrics['macro_f1']:.4f} < 0.60")


def main():
    ap = argparse.ArgumentParser(description="计算 AI 分类 F1 分数")
    ap.add_argument("--input", default=DEFAULT_DATASET, help="标注数据集路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"[error] 数据集不存在: {args.input}")
        print("[info] 请先运行: python evals/create_dataset.py --count 30 --seed 42")
        sys.exit(1)

    entries = load_dataset(args.input)

    if not entries:
        print("[warn] 数据集中没有已标注的样本")
        print("[info] 请编辑 dataset.jsonl，填写 expected_category 字段")
        sys.exit(0)

    metrics = compute_metrics(entries)

    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print_report(metrics)


if __name__ == "__main__":
    main()
