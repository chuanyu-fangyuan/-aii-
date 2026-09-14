#!/usr/bin/env python3
"""AI 情报站 - 每日采集脚本

从多个独立信息源抓取 AI 相关资讯，清洗去重后写入 SQLite，
并导出前端消费的 data.json（含关系图谱数据）。

特性：
- 幂等：重复导入同一输入不会产生重复记录（URL / 标题双哈希去重）
- 容错：单个来源失败不影响其他来源与已有数据，状态写入 update_runs
- 时间口径：发布时间与采集时间分离存储；内部统一 UTC，展示层转 Asia/Shanghai
"""

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

try:
    import feedparser
except ImportError:
    sys.exit("缺少依赖：pip install feedparser")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "news.db")
EXPORT_PATH = os.path.join(BASE_DIR, "web", "data.json")
USER_AGENT = "ai-daily-brief/1.0 (+https://github.com/; personal news aggregator)"
HTTP_TIMEOUT = 20
# 只保留最近 N 天的资讯参与展示（存储保留全部，导出时裁剪）
EXPORT_WINDOW_DAYS = 30

SOURCES = [
    {
        "id": "hackernews",
        "name": "Hacker News",
        "type": "hn_api",
        "url": "https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story&hitsPerPage=40",
    },
    {
        "id": "techcrunch",
        "name": "TechCrunch AI",
        "type": "rss",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
    },
    {
        "id": "theverge",
        "name": "The Verge AI",
        "type": "rss",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    },
    {
        "id": "arxiv",
        "name": "arXiv cs.AI",
        "type": "rss",
        "url": "https://rss.arxiv.org/rss/cs.AI",
    },
]

# ---------------------------------------------------------------- 去重工具

TRACKING_PARAMS = re.compile(
    r"^(utm_|fbclid$|gclid$|ref$|ref_src$|spm$|mc_cid$|mc_eid$)", re.I
)


def canonical_url(url: str) -> str:
    """去掉跟踪参数、统一小写 host、去末尾斜杠，用于 URL 级去重。"""
    if not url:
        return ""
    url = html.unescape(url.strip())
    p = urllib.parse.urlsplit(url)
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = urllib.parse.parse_qsl(p.query, keep_blank_values=False)
    query = [(k, v) for k, v in query if not TRACKING_PARAMS.match(k)]
    query.sort()
    path = p.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(("https", host, path, urllib.parse.urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def title_hash(title: str) -> str:
    """标题归一化哈希：小写、去标点、压空白，用于标题级去重。"""
    t = re.sub(r"[^\w一-鿿]+", " ", (title or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- HTTP


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


# ---------------------------------------------------------------- 解析


def parse_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def fetch_hn_api(source: dict) -> list:
    data = json.loads(http_get(source["url"]))
    items = []
    for hit in data.get("hits", []):
        title = (hit.get("title") or "").strip()
        link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        if not title:
            continue
        published = hit.get("created_at")  # ISO 8601 UTC
        items.append(
            {
                "title": title,
                "url": link,
                "summary": f"Hacker News 热帖 · {hit.get('points', 0)} 分 · {hit.get('num_comments') or 0} 评论",
                "published_at": published if published else None,
                "source_id": source["id"],
                "source_name": source["name"],
            }
        )
    return items


def fetch_rss(source: dict) -> list:
    raw = http_get(source["url"])
    feed = feedparser.parse(raw)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"RSS 解析失败: {getattr(feed, 'bozo_exception', 'unknown')}")
    items = []
    for entry in feed.entries[:30]:
        title = (entry.get("title") or "").strip()
        link = entry.get("link") or ""
        if not title or not link:
            continue
        published = None
        for key in ("published_parsed", "updated_parsed"):
            t = entry.get(key)
            if t:
                published = parse_dt(datetime.fromtimestamp(time.mktime(t), tz=timezone.utc))
                break
        summary = ""
        raw_summary = entry.get("summary") or ""
        if raw_summary:
            summary = re.sub(r"<[^>]+>", "", raw_summary)
            summary = html.unescape(summary).strip()
            # 去掉 arXiv 的模板前缀 "arXiv:xxxx.v1 Announce Type: new Abstract:"
            summary = re.sub(r"^arXiv:[\w.\-/]+.*?Abstract:\s*", "", summary, flags=re.S)
            if len(summary) > 200:
                summary = summary[:197] + "..."
        items.append(
            {
                "title": title,
                "url": link,
                "summary": summary,
                "published_at": published,
                "source_id": source["id"],
                "source_name": source["name"],
            }
        )
    return items


FETCHERS = {"hn_api": fetch_hn_api, "rss": fetch_rss}

# ---------------------------------------------------------------- 存储


def init_db(conn: sqlite3.Connection):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url_hash TEXT NOT NULL UNIQUE,
            title_hash TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            summary TEXT DEFAULT '',
            source_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            published_at TEXT,           -- 原始发布时间（UTC ISO），可能为 NULL
            published_unknown INTEGER NOT NULL DEFAULT 0,
            fetched_at TEXT NOT NULL,    -- 采集时间（UTC ISO）
            UNIQUE(title_hash, source_id)
        );
        CREATE TABLE IF NOT EXISTS update_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT NOT NULL,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL,        -- ok / failed / no_new
            fetched INTEGER DEFAULT 0,
            inserted INTEGER DEFAULT 0,
            message TEXT DEFAULT ''
        );
        """
    )


def upsert_items(conn: sqlite3.Connection, items: list) -> int:
    now = parse_dt(datetime.now(timezone.utc))
    inserted = 0
    for it in items:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO news
                   (url_hash, title_hash, title, url, summary, source_id,
                    source_name, published_at, published_unknown, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    url_hash(it["url"]),
                    title_hash(it["title"]),
                    it["title"],
                    it["url"],
                    it.get("summary", ""),
                    it["source_id"],
                    it["source_name"],
                    it["published_at"],
                    0 if it["published_at"] else 1,
                    now,
                ),
            )
            inserted += cur.rowcount
        except sqlite3.Error:
            continue
    return inserted


# ---------------------------------------------------------------- 关键词 / 图谱

# 常见 AI 实体词典（优先按整体匹配），可按需扩充
ENTITY_LEXICON = [
    "OpenAI", "ChatGPT", "GPT-5", "GPT-4", "GPT-4o", "Anthropic", "Claude",
    "Google DeepMind", "DeepMind", "Gemini", "Meta", "Llama", "Microsoft",
    "Copilot", "Apple", "NVIDIA", "Tesla", "xAI", "Grok", "Mistral",
    "Hugging Face", "Stability AI", "Midjourney", "Sora", "DeepSeek",
    "Qwen", "Kimi", "Transformer", "Diffusion", "RAG", "Agent", "AGI",
    "LLM", "Machine Learning", "Deep Learning", "Neural Network",
    "Reinforcement Learning", "Fine-tuning", "Inference", "Robotics",
    "Autonomous", "Regulation", "Copyright", "Benchmark",
    "Multimodal", "Embedding", "Tokenizer", "Prompt", "Hallucination",
    "Alignment", "Reasoning", "Pretraining", "Dataset", "GPU",
    "Open Source", "Safety", "Alignment", "Startup", "Funding",
    "Acquisition", "Chatbot", "Voice", "Video Generation", "Agentic",
    "World Model", "Quantization", "Distillation", "Edge AI", "Chip",
]

STOPWORDS = set(
    "the a an and or of to in on for with at by from is are was were be been "
    "it its this that these those as not no but if then than so such more most "
    "new how what why when where who will would can could has have had do does "
    "you your we our they their he she his her about after before over under "
    "into out up down just also now says said report reports ai "
    "across announce abstract type via using based toward towards open model "
    "models arxiv http https com www language large systems system "
    "data time week day year years people work way ways make makes take".split()
)

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")


def extract_keywords(text: str, freq: dict, min_freq: int = 2) -> list:
    """实体词典精确匹配 + 高频实义词（出现 >= min_freq 次的跨文档词）。"""
    found = []
    low = text.lower()
    for ent in ENTITY_LEXICON:
        # 允许英文复数后缀（LLM/LLMs、Agent/Agents）
        suffix = "" if ent.lower().endswith("s") else "s?"
        if re.search(r"(?<![\w-])" + re.escape(ent.lower()) + suffix + r"(?![\w-])", low):
            found.append(ent)
    for tok in set(m.group(0) for m in TOKEN_RE.finditer(text)):
        t = tok.lower().strip("-")
        if t in STOPWORDS or len(t) < 4:
            continue
        if freq.get(t, 0) >= min_freq:
            found.append(tok)
    # 去重（单复数、大小写归一；实体词典优先）、限量
    seen, out = set(), []
    for k in found:
        kl = k.lower()
        if kl in seen or kl.rstrip("s") in seen or (kl + "s") in seen:
            continue
        seen.add(kl)
        out.append(k)
    return out[:8]


def build_graph(rows: list) -> dict:
    """节点 = 新闻 + 关键词；边 = 新闻-关键词归属。共享关键词形成话题簇。"""
    # 高频词只从标题统计：标题信噪比远高于摘要
    freq = {}
    for r in rows:
        for tok in set(m.group(0).lower().strip("-") for m in TOKEN_RE.finditer(r["title"])):
            if tok not in STOPWORDS and len(tok) >= 4:
                freq[tok] = freq.get(tok, 0) + 1

    nodes, links = [], []
    kw_nodes = {}
    for r in rows:
        nid = f"n{r['id']}"
        nodes.append(
            {
                "id": nid,
                "type": "news",
                "label": r["title"],
                "news_id": r["id"],
                "source_name": r["source_name"],
                "time": r["published_at"] or r["fetched_at"],
            }
        )
        kws = extract_keywords(f"{r['title']} {r['summary']}", freq)
        for kw in kws:
            kid = f"k:{kw.lower()}"
            if kid not in kw_nodes:
                kw_nodes[kid] = {"id": kid, "type": "keyword", "label": kw, "count": 0}
                nodes.append(kw_nodes[kid])
            kw_nodes[kid]["count"] += 1
            links.append({"source": nid, "target": kid})
    # 只保留连接 >= 2 条新闻的关键词节点，避免图谱过噪
    degree = {}
    for l in links:
        degree[l["target"]] = degree.get(l["target"], 0) + 1
    keep_kw = {k for k, d in degree.items() if d >= 2}
    nodes = [n for n in nodes if n["type"] == "news" or n["id"] in keep_kw]
    links = [l for l in links if l["target"] in keep_kw]
    return {"nodes": nodes, "links": links}


# ---------------------------------------------------------------- 导出

SHANGHAI = timezone(timedelta(hours=8))


def build_digest(rows: list, graph: dict) -> dict:
    """今日速读：按关键词把「今天（Asia/Shanghai）」的新闻聚类成主题。
    规则聚合（非 LLM 生成）：主题 = 当日关联新闻最多的关键词，附各主题下的新闻链接。"""
    today = datetime.now(SHANGHAI).date().isoformat()
    kw_label = {n["id"]: n["label"] for n in graph["nodes"] if n["type"] == "keyword"}
    news_kw = {}  # "n<id>" -> [keyword label]
    for l in graph["links"]:
        nid, kid = l["source"], l["target"]
        if kid in kw_label:
            news_kw.setdefault(nid, []).append(kw_label[kid])

    todays = []
    for r in rows:
        t = r["published_at"] or r["fetched_at"]
        d = datetime.fromisoformat(t).astimezone(SHANGHAI).date().isoformat()
        if d == today:
            todays.append(r)

    topics = {}
    for r in todays:
        for kw in news_kw.get(f"n{r['id']}", []):
            topics.setdefault(kw, []).append(r["id"])
    top = sorted(topics.items(), key=lambda kv: -len(kv[1]))[:6]

    return {
        "date": today,
        "total_today": len(todays),
        "note": "由规则按关键词自动聚合，非 AI 生成内容；未补造任何事实。",
        "topics": [
            {"keyword": kw, "count": len(ids), "news_ids": ids}
            for kw, ids in top
        ],
    }


def export_json(conn: sqlite3.Connection):
    cutoff = parse_dt(datetime.now(timezone.utc) - timedelta(days=EXPORT_WINDOW_DAYS))
    rows = [
        dict(r)
        for r in conn.execute(
            """SELECT id, title, url, summary, source_id, source_name,
                      published_at, published_unknown, fetched_at
               FROM news
               WHERE COALESCE(published_at, fetched_at) >= ?
               ORDER BY COALESCE(published_at, fetched_at) DESC""",
            (cutoff,),
        ).fetchall()
    ]
    graph = build_graph(rows)
    for r in rows:
        r["summary"] = re.sub(r"^arXiv:[\w.\-/]+.*?Abstract:\s*", "", r["summary"] or "", flags=re.S)

    runs = [
        dict(r)
        for r in conn.execute(
            """SELECT source_id, status, fetched, inserted, message, run_at
               FROM update_runs WHERE id IN (
                   SELECT MAX(id) FROM update_runs GROUP BY source_id
               )"""
        ).fetchall()
    ]
    meta = {
        "generated_at": parse_dt(datetime.now(timezone.utc)),
        "timezone_display": "Asia/Shanghai",
        "total": len(rows),
        "sources": runs,
    }
    digest = build_digest(rows, graph)
    os.makedirs(os.path.dirname(EXPORT_PATH), exist_ok=True)
    with open(EXPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "news": rows, "graph": graph, "digest": digest}, f, ensure_ascii=False)
    print(f"[export] {len(rows)} 条资讯, 图谱 {len(graph['nodes'])} 节点 -> {EXPORT_PATH}")


# ---------------------------------------------------------------- 主流程


def run(sources, only=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    run_at = parse_dt(datetime.now(timezone.utc))

    for src in sources:
        if only and src["id"] != only:
            continue
        status, message, fetched, inserted = "ok", "", 0, 0
        try:
            items = FETCHERS[src["type"]](src)
            fetched = len(items)
            inserted = upsert_items(conn, items)
            if fetched == 0:
                status, message = "no_new", "来源返回 0 条"
            elif inserted == 0:
                status = "no_new"  # 有抓取但无新增：与抓取失败明确区分
        except Exception as e:  # 单源失败不影响其他源与已有数据
            status, message = "failed", f"{type(e).__name__}: {e}"
        conn.execute(
            "INSERT INTO update_runs (run_at, source_id, status, fetched, inserted, message) VALUES (?,?,?,?,?,?)",
            (run_at, src["id"], status, fetched, inserted, message[:300]),
        )
        conn.commit()
        print(f"[{src['id']}] {status}: fetched={fetched} inserted={inserted} {message}")

    export_json(conn)
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只采集指定来源 id")
    ap.add_argument("--fail-source", help="测试用：强制指定来源失败（注入坏 URL）")
    args = ap.parse_args()

    sources = SOURCES
    if args.fail_source:
        for s in sources:
            if s["id"] == args.fail_source:
                s["url"] = "https://invalid.example.com/feed.xml"
    run(sources, only=args.only)
