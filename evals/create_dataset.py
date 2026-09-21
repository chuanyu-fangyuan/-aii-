#!/usr/bin/env python3
"""生成评测标注集

从已分析的新闻中随机抽样，生成标注模板。
人工填写 expected_category 和 expected_verification 后，
用于 eval_classify.py 计算 F1。

用法：
  python evals/create_dataset.py --count 30 --seed 42
"""

import argparse
import json
import os
import random
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from db import SQLITE_PATH, init_sqlite


def create_dataset(count: int, seed: int):
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    init_sqlite(conn)

    # 只从已分析完成的新闻中抽样
    rows = conn.execute(
        """SELECT id, title, source_id, source_name, ai_category, ai_summary_zh,
                  importance, verification
           FROM news
           WHERE ai_status = 'done'
           ORDER BY id"""
    ).fetchall()

    if not rows:
        print("[warn] 没有已分析的新闻（ai_status='done'），请先运行 analyze.py")
        print("[info] 创建空标注模板，待分析完成后填写")
        rows = conn.execute(
            """SELECT id, title, source_id, source_name,
                      NULL as ai_category, NULL as ai_summary_zh,
                      0 as importance, NULL as verification
               FROM news
               WHERE COALESCE(published_at, fetched_at) >= datetime('now', '-7 days')
               ORDER BY RANDOM()
               LIMIT ?""",
            (count,),
        ).fetchall()

    random.seed(seed)
    sampled = random.sample(list(rows), min(count, len(rows)))

    os.makedirs(os.path.join(BASE_DIR, "evals"), exist_ok=True)
    output_path = os.path.join(BASE_DIR, "evals", "dataset.jsonl")

    with open(output_path, "w", encoding="utf-8") as f:
        for r in sampled:
            entry = {
                "news_id": r["id"],
                "title": r["title"],
                "source_id": r["source_id"],
                "source_name": r["source_name"],
                "ai_category": r["ai_category"],
                "ai_summary_zh": r["ai_summary_zh"],
                "importance": r["importance"],
                "verification": r["verification"],
                # 人工标注字段（待填写）
                "expected_category": "",
                "expected_verification": "",
                "note": "",
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"[done] 标注集已生成: {output_path}")
    print(f"  抽样: {len(sampled)} 条 (seed={seed})")
    print(f"  请人工填写 expected_category 和 expected_verification 字段")

    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=30, help="抽样数量")
    ap.add_argument("--seed", type=int, default=42, help="随机种子")
    args = ap.parse_args()
    create_dataset(args.count, args.seed)
