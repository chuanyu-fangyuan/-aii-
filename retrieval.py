"""混合检索层

BM25 + 向量检索 + RRF 融合 + 时间衰减。
接口：search(query, top_k=5) → List[SearchResult]
"""

import math
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np
from rank_bm25 import BM25Okapi

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE_DIR, "data", "news.db")

RRF_K = 60
TIME_DECAY_HALF_LIFE_DAYS = 30
VECTOR_WEIGHT = 0.6
BM25_WEIGHT = 0.4


@dataclass
class SearchResult:
    news_id: int
    title: str
    url: str
    source_name: str
    ai_category: Optional[str]
    ai_summary_zh: Optional[str]
    published_at: Optional[str]
    score: float
    vector_rank: int = 0
    bm25_rank: int = 0


def _tokenize(text: str) -> List[str]:
    text = text.lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]", " ", text)
    tokens = []
    for word in text.split():
        if re.search(r"[\u4e00-\u9fff]", word):
            tokens.extend(list(word))
        elif len(word) > 1:
            tokens.append(word)
    return tokens


def _load_indexed_docs(conn):
    rows = conn.execute(
        "SELECT id, title, url, source_name, ai_category, ai_summary_zh, "
        "published_at, embedding "
        "FROM news WHERE embedding IS NOT NULL"
    ).fetchall()
    return rows


def _build_bm25(rows):
    corpus = []
    for r in rows:
        parts = [r["title"]]
        if r["ai_summary_zh"]:
            parts.append(r["ai_summary_zh"])
        if r["ai_category"]:
            parts.append(r["ai_category"])
        corpus.append(_tokenize(" ".join(parts)))
    return BM25Okapi(corpus)


def _vector_search(query_emb: np.ndarray, all_embs: np.ndarray, top_k: int) -> List[int]:
    sims = all_embs @ query_emb
    indices = np.argsort(-sims)[:top_k]
    return [(int(idx), float(sims[idx])) for idx in indices]


def _bm25_search(bm25: BM25Okapi, query: str, top_k: int) -> List[int]:
    tokens = _tokenize(query)
    scores = bm25.get_scores(tokens)
    indices = np.argsort(-scores)[:top_k]
    return [(int(idx), float(scores[idx])) for idx in indices if scores[idx] > 0]


def _time_decay_factor(published_at: Optional[str], now: datetime) -> float:
    if not published_at:
        return 0.5
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        age_days = max(0, (now - dt).total_seconds() / 86400)
        return math.pow(0.5, age_days / TIME_DECAY_HALF_LIFE_DAYS)
    except (ValueError, TypeError):
        return 0.5


def _rrf_fusion(vector_results, bm25_results, k=RRF_K):
    scores = {}
    for rank, (idx, _) in enumerate(vector_results):
        scores[idx] = scores.get(idx, 0) + VECTOR_WEIGHT / (k + rank + 1)
    for rank, (idx, _) in enumerate(bm25_results):
        scores[idx] = scores.get(idx, 0) + BM25_WEIGHT / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])


def _load_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("BAAI/bge-small-zh-v1.5")


_model_cache = None


def _get_model():
    global _model_cache
    if _model_cache is None:
        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        _model_cache = _load_model()
    return _model_cache


def search(query: str, top_k: int = 5, vector_factor: int = 3) -> List[SearchResult]:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row

    rows = _load_indexed_docs(conn)
    if not rows:
        conn.close()
        return []

    row_by_idx = {i: r for i, r in enumerate(rows)}

    all_embs = np.array(
        [np.frombuffer(r["embedding"], dtype=np.float32) for r in rows],
        dtype=np.float32,
    )

    model = _get_model()
    query_emb = model.encode(query, normalize_embeddings=True).astype(np.float32)

    vec_top_k = top_k * vector_factor
    vector_results = _vector_search(query_emb, all_embs, vec_top_k)
    bm25 = _build_bm25(rows)
    bm25_results = _bm25_search(bm25, query, vec_top_k)

    vec_rank_map = {idx: rank for rank, (idx, _) in enumerate(vector_results)}
    bm25_rank_map = {idx: rank for rank, (idx, _) in enumerate(bm25_results)}

    fused = _rrf_fusion(vector_results, bm25_results)

    now = datetime.now(timezone.utc)
    results = []
    for idx, rrf_score in fused:
        r = row_by_idx[idx]
        decay = _time_decay_factor(r["published_at"], now)
        final_score = rrf_score * decay

        results.append(SearchResult(
            news_id=r["id"],
            title=r["title"],
            url=r["url"],
            source_name=r["source_name"],
            ai_category=r["ai_category"],
            ai_summary_zh=r["ai_summary_zh"],
            published_at=r["published_at"],
            score=final_score,
            vector_rank=vec_rank_map.get(idx, -1) + 1,
            bm25_rank=bm25_rank_map.get(idx, -1) + 1,
        ))

        if len(results) >= top_k:
            break

    conn.close()
    return results


def search_pure_vector(query: str, top_k: int = 5) -> List[SearchResult]:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row

    rows = _load_indexed_docs(conn)
    if not rows:
        conn.close()
        return []

    all_embs = np.array(
        [np.frombuffer(r["embedding"], dtype=np.float32) for r in rows],
        dtype=np.float32,
    )

    model = _get_model()
    query_emb = model.encode(query, normalize_embeddings=True).astype(np.float32)
    vector_results = _vector_search(query_emb, all_embs, top_k)

    results = []
    for idx, score in vector_results:
        r = rows[idx]
        results.append(SearchResult(
            news_id=r["id"],
            title=r["title"],
            url=r["url"],
            source_name=r["source_name"],
            ai_category=r["ai_category"],
            ai_summary_zh=r["ai_summary_zh"],
            published_at=r["published_at"],
            score=score,
        ))

    conn.close()
    return results


if __name__ == "__main__":
    test_queries = [
        "OpenAI 最新发布",
        "AI 芯片进展",
        "开源大模型",
        "AI 监管政策",
        "自动驾驶",
    ]
    for q in test_queries:
        print(f"\n{'='*60}")
        print(f"Query: {q}")
        print(f"{'='*60}")
        results = search(q, top_k=3)
        for i, r in enumerate(results, 1):
            print(f"  {i}. [{r.ai_category}] {r.title[:50]}")
            print(f"     score={r.score:.4f} vec_rank={r.vector_rank} bm25_rank={r.bm25_rank}")
            if r.ai_summary_zh:
                print(f"     {r.ai_summary_zh[:60]}...")
