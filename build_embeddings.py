"""Embedding 流水线

使用 bge-small-zh-v1.5 对已分析新闻计算向量嵌入，存入 news.embedding 列。
增量逻辑：只对 ai_status='done' AND embedding IS NULL 的记录计算。

环境变量：
  HF_ENDPOINT  — HuggingFace 镜像（国内设 https://hf-mirror.com）
"""

import argparse
import os
import sqlite3
import time

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE_DIR, "data", "news.db")

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
EMBEDDING_DIM = 512


def get_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(news)").fetchall()}
    if "embedding" not in existing_cols:
        conn.execute("ALTER TABLE news ADD COLUMN embedding BLOB")
        conn.commit()
    return conn


def load_model():
    from sentence_transformers import SentenceTransformer
    print(f"[embedding] 加载模型 {MODEL_NAME} ...")
    t0 = time.time()
    model = SentenceTransformer(MODEL_NAME)
    print(f"[embedding] 模型加载完成 ({time.time() - t0:.1f}s)")
    return model


def build_embeddings(model, batch_size: int = 64):
    conn = get_conn()

    rows = conn.execute(
        "SELECT id, title, ai_summary_zh FROM news "
        "WHERE ai_status = 'done' AND embedding IS NULL "
        "ORDER BY id"
    ).fetchall()

    if not rows:
        print("[embedding] 无待计算记录")
        return

    print(f"[embedding] 待计算: {len(rows)} 条")

    texts = []
    ids = []
    for r in rows:
        parts = [r["title"]]
        if r["ai_summary_zh"]:
            parts.append(r["ai_summary_zh"])
        texts.append("\n".join(parts))
        ids.append(r["id"])

    t0 = time.time()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
    )

    for i, news_id in enumerate(ids):
        conn.execute(
            "UPDATE news SET embedding = ? WHERE id = ?",
            (embeddings[i].astype(np.float32).tobytes(), news_id),
        )
    conn.commit()

    elapsed = time.time() - t0
    total = conn.execute(
        "SELECT COUNT(*) FROM news WHERE embedding IS NOT NULL"
    ).fetchone()[0]
    conn.close()

    print(f"[embedding] 完成: {len(ids)} 条新计算, 累计 {total} 条, 耗时 {elapsed:.1f}s")


def verify_consistency(model):
    conn = get_conn()
    row = conn.execute(
        "SELECT id, title, ai_summary_zh, embedding FROM news "
        "WHERE embedding IS NOT NULL LIMIT 1"
    ).fetchone()
    if not row:
        print("[embedding] 无可验证记录")
        return

    stored = np.frombuffer(row["embedding"], dtype=np.float32)
    parts = [row["title"]]
    if row["ai_summary_zh"]:
        parts.append(row["ai_summary_zh"])
    recomputed = model.encode("\n".join(parts), normalize_embeddings=True)

    cos_sim = float(np.dot(stored, recomputed))
    print(f"[embedding] 一致性验证: news_id={row['id']}, cos_sim={cos_sim:.6f}")
    if cos_sim > 0.99:
        print("[embedding] ✅ 通过（> 0.99）")
    else:
        print("[embedding] ❌ 不一致！")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--verify", action="store_true", help="验证已计算 embedding 一致性")
    args = parser.parse_args()

    if not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        print("[embedding] 设置 HF_ENDPOINT=https://hf-mirror.com")

    model = load_model()

    if args.verify:
        verify_consistency(model)
    else:
        build_embeddings(model, batch_size=args.batch_size)
