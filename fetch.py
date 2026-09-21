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
SHANGHAI = timezone(timedelta(hours=8))

# ---------------------------------------------------------------- 数据治理（遗忘策略）
# 资讯是「流式」数据：长期只增不减，列表和关系图谱都会变得不可用。
# 这里用四层不同粒度的遗忘，越靠前越激进：
#   ① 采集配额 —— 限制每天写入多少条，从源头控制增速
#   ② 记忆衰减 —— 每条资讯有「记忆强度」，按半衰期指数衰减，越旧越弱
#   ③ 图谱容量 —— 只在强度最高的有限节点上作图，其余遗忘（列表仍可阅读）
#   ④ 归档保留 —— 库内超过保留期的记录删除并回收空间
# 四层的参数可以独立调整，互不影响。
DAILY_INGEST_LIMIT = 120     # 每日新增入库上限（跨源合计，按北京时间自然日）
RUNS_PER_DAY = 8             # 每天运行轮数，需与 .github/workflows/update.yml 的 cron 一致
GRAPH_HALF_LIFE_HOURS = 30   # 记忆半衰期：30 小时后权重减半，控制衰减速度
GRAPH_WINDOW_DAYS = 7        # 图谱硬边界：超过这个年龄的资讯一律不进图
GRAPH_MAX_NEWS = 240         # 图谱内新闻节点上限（= 2 个采集日，与半衰期口径一致）
GRAPH_MAX_KEYWORDS = 100     # 图谱内关键词节点上限（按记忆强度保留最高的）
MIN_KEYWORD_DEGREE = 2       # 关键词至少关联 N 条新闻才成为节点
GRAPH_FORGET_THRESHOLD = 0.12  # 关键词记忆强度低于此值即遗忘（≈ 91 小时半衰期衰减后）
EXPORT_WINDOW_DAYS = 30      # 前端「全部」视图的时间窗口
EXPORT_MAX_ITEMS = 1500      # 导出条数硬上限（防止 data.json 无限膨胀）
DB_RETENTION_DAYS = 90       # 库内记录保留期，超出即删除（news.db 会被提交进仓库，体积需可控）

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
    # 增量迁移：给已存在的 news 表添加 AI 字段
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(news)").fetchall()}
    for col_name, sql in [
        ("ai_category", "ALTER TABLE news ADD COLUMN ai_category TEXT"),
        ("ai_summary_zh", "ALTER TABLE news ADD COLUMN ai_summary_zh TEXT"),
        ("importance", "ALTER TABLE news ADD COLUMN importance INTEGER NOT NULL DEFAULT 0"),
        ("verification", "ALTER TABLE news ADD COLUMN verification TEXT"),
        ("verification_note", "ALTER TABLE news ADD COLUMN verification_note TEXT"),
        ("entities_json", "ALTER TABLE news ADD COLUMN entities_json TEXT DEFAULT '[]'"),
        ("ai_status", "ALTER TABLE news ADD COLUMN ai_status TEXT NOT NULL DEFAULT 'pending'"),
    ]:
        if col_name not in existing_cols:
            conn.execute(sql)
    conn.commit()


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


def ingested_today(conn: sqlite3.Connection) -> int:
    """今天（Asia/Shanghai 自然日）已入库条数，用于计算剩余采集配额。

    注意用上海时区而不是 UTC：配额是给「用户看到的今天」定的，
    否则北京时间早上 8 点会算成前一天，配额口径与页面口径不一致。
    """
    start_local = datetime.now(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = parse_dt(start_local.astimezone(timezone.utc))
    row = conn.execute(
        "SELECT COUNT(*) FROM news WHERE fetched_at >= ?", (start_utc,)
    ).fetchone()
    return row[0] if row else 0


def prune_old(conn: sqlite3.Connection) -> int:
    """归档保留：删除超过保留期的记录，并回收文件空间。

    news.db 会随每次运行提交进仓库，只增不减会让仓库体积线性膨胀；
    VACUUM 用来把删除后的空闲页真正还给文件系统（否则文件大小不降）。
    """
    cutoff = parse_dt(datetime.now(timezone.utc) - timedelta(days=DB_RETENTION_DAYS))
    removed = conn.execute(
        "DELETE FROM news WHERE COALESCE(published_at, fetched_at) < ?", (cutoff,)
    ).rowcount
    conn.execute("DELETE FROM update_runs WHERE run_at < ?", (cutoff,))
    conn.commit()
    if removed:
        conn.execute("VACUUM")  # 必须在事务外执行
    return max(removed, 0)


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
    # 源名称词：不携带话题信息，却几乎出现在每条同源新闻里
    "news hacker techcrunch verge "
    "data time week day year years people work way ways make makes take show".split()
)

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")

# 关键词提取时需剥离的 source 元信息前缀。
# 例：HN 的 summary 是「Hacker News 热帖 · 12 分 · 3 评论」——不含任何正文内容，
# 却出现在每一条 HN 新闻里。不剥离的话 "News"/"Hacker" 会命中全部新闻，
# 生成一个度数等于全部新闻数的假关键词节点（实测曾达 694），
# 既污染图谱语义，又把力导向布局拽成一个巨型星形、显著拖慢渲染。
KEYWORD_META_RE = re.compile(
    r"^(?:Hacker News 热帖[^\n]*|arXiv:[\w.\-/]+[^\n]*?Abstract:\s*)", re.I
)


def keyword_text(row) -> str:
    """构造用于关键词提取的文本：标题 + 剥离元信息后的摘要。

    注意：展示用的 summary 不做改动（前端要显示分数），只在这里剥离。
    """
    summary = KEYWORD_META_RE.sub("", row["summary"] or "").strip()
    return f"{row['title']} {summary}".strip()


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


def memory_strength(ts: str, now: datetime) -> float:
    """记忆强度：按半衰期指数衰减，刚采集的为 1.0，每过一个半衰期减半。

    这是「遗忘机制」的核心量纲——图谱不再按「时间倒序取前 N 条」这种硬截断选点，
    而是按强度排序取前 N 条：一条 3 天前但被反复讨论的资讯，
    可以比一条 5 小时前的孤立资讯更值得留在图上。
    """
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - dt).total_seconds() / 3600.0)
    return 0.5 ** (age_hours / GRAPH_HALF_LIFE_HOURS)


def build_graph(rows: list, strengths: dict) -> tuple:
    """节点 = 新闻 + 关键词；边 = 新闻-关键词归属。共享关键词形成话题簇。

    返回 (graph, stats)：stats 记录本轮遗忘了多少关键词，用于导出与核对。
    """
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
        st = strengths.get(r["id"], 1.0)
        nodes.append(
            {
                "id": nid,
                "type": "news",
                "label": r["title"],
                "news_id": r["id"],
                "source_name": r["source_name"],
                "time": r["published_at"] or r["fetched_at"],
                "strength": round(st, 4),
            }
        )
        # 用 keyword_text 而非 title+summary：剥离「HN 热帖 · N 分」这类元信息，
        # 否则源名称词会连上全部同源新闻，形成假关键词节点
        kws = extract_keywords(keyword_text(r), freq)
        for kw in kws:
            kid = f"k:{kw.lower()}"
            if kid not in kw_nodes:
                kw_nodes[kid] = {"id": kid, "type": "keyword", "label": kw,
                                 "count": 0, "strength": 0.0}
                nodes.append(kw_nodes[kid])
            kw_nodes[kid]["count"] += 1
            # 关键词强度 = 关联新闻强度之和：话题的热度会随着相关资讯变旧而自然衰减
            kw_nodes[kid]["strength"] += st
            links.append({"source": nid, "target": kid})

    # 两级遗忘：先按最低关联度剔除长尾噪声，再按记忆强度阈值剔除已经衰减殆尽的话题，
    # 最后按强度截断到 GRAPH_MAX_KEYWORDS——关键词节点数量直接决定图的密度与渲染成本
    candidates = [n for n in kw_nodes.values() if n["count"] >= MIN_KEYWORD_DEGREE]
    survived = [n for n in candidates if n["strength"] >= GRAPH_FORGET_THRESHOLD]
    survived.sort(key=lambda n: (-n["strength"], -n["count"]))
    kept = survived[:GRAPH_MAX_KEYWORDS]
    keep_ids = {n["id"] for n in kept}
    for n in kept:
        n["strength"] = round(n["strength"], 4)

    nodes = [n for n in nodes if n["type"] == "news" or n["id"] in keep_ids]
    links = [l for l in links if l["target"] in keep_ids]
    stats = {
        "keywords_total": len(kw_nodes),
        "keywords_forgotten": len(kw_nodes) - len(kept),
        "keywords_below_degree": len(kw_nodes) - len(candidates),
        "keywords_below_strength": len(candidates) - len(survived),
    }
    return {"nodes": nodes, "links": links}, stats


# ---------------------------------------------------------------- 导出


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


# ---------------------------------------------------------------- 数据新鲜度防线
# 真实教训：本地 news.db 与云端 Actions 累积的库分叉后，用本地旧库重导出
# 会把站点资讯从 927 条悄悄降回 334 条——数据变少不报错，极难察觉。
# 因此每次导出前检查库内最新采集时间：落后超过 24 小时说明本库大概率
# 不是最新产物（云端流水线在持续写入），必须显式警告而不是静默导出。
STALE_DB_WARNING_HOURS = 24


def warn_if_stale(conn: sqlite3.Connection) -> None:
    # 用 update_runs 的最后运行时间而非 MAX(fetched_at)：后者会被任何一次
    # 本地采集刷新，掩盖「这个库早已落后于云端」的事实。
    latest = conn.execute("SELECT MAX(run_at) FROM update_runs").fetchone()[0]
    if not latest:
        print(
            "[warn] 库内没有任何采集记录（update_runs 为空），导出的数据可能不完整。",
            file=sys.stderr,
        )
        return
    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(latest)).total_seconds() / 3600
    if age_h > STALE_DB_WARNING_HOURS:
        print(
            f"[warn] 当前库最新采集时间为 {latest}（落后 {age_h:.0f} 小时）。"
            "本地库可能落后于云端流水线，导出结果会缺少近期数据；"
            "请先 git pull 或联网运行 python fetch.py 再导出。",
            file=sys.stderr,
        )


def export_json(conn: sqlite3.Connection, pruned: int = 0):
    now = datetime.now(timezone.utc)
    cutoff = parse_dt(now - timedelta(days=EXPORT_WINDOW_DAYS))
    rows = [
        dict(r)
        for r in conn.execute(
            """SELECT id, title, url, summary, source_id, source_name,
                      published_at, published_unknown, fetched_at,
                      ai_category, ai_summary_zh, importance,
                      verification, verification_note, entities_json
               FROM news
               WHERE COALESCE(published_at, fetched_at) >= ?
               ORDER BY COALESCE(published_at, fetched_at) DESC
               LIMIT ?""",
            (cutoff, EXPORT_MAX_ITEMS),
        ).fetchall()
    ]
    total_db = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]

    # 图谱记忆窗口：更早的资讯在列表里仍可阅读，但不再进入图谱。
    # 图谱的成本≈节点数的平方级，必须比列表窗口短得多才不会被历史库存拖慢。
    graph_cutoff = parse_dt(now - timedelta(days=GRAPH_WINDOW_DAYS))
    recent = [r for r in rows if (r["published_at"] or r["fetched_at"]) >= graph_cutoff]
    strengths = {
        r["id"]: memory_strength(r["published_at"] or r["fetched_at"], now) for r in recent
    }
    # 按记忆强度（而非纯时间）排序取前 N：让「旧但仍被热议」的话题留在图上，
    # 「新但孤立」的条目优先被遗忘。这条排序是图谱规模可预测的关键。
    ranked = sorted(recent, key=lambda r: (-strengths[r["id"]], -r["id"]))
    kept = ranked[:GRAPH_MAX_NEWS]
    graph, gstats = build_graph(kept, strengths)

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
        "generated_at": parse_dt(now),
        "timezone_display": "Asia/Shanghai",
        "total": len(rows),
        # 归档条数 vs 展示条数：两个数不同是遗忘策略生效的正常结果，明确区分避免误读为数据丢失
        "archived_total": total_db,
        "sources": runs,
        # 遗忘策略随数据导出，前端据此说明「为什么图谱比列表少」，
        # 也便于评审核对页面行为与配置一致（与 schedule 同理，不写死在文案里）
        "window": {
            "graph_days": GRAPH_WINDOW_DAYS,
            "graph_half_life_hours": GRAPH_HALF_LIFE_HOURS,
            "graph_max_news": GRAPH_MAX_NEWS,
            "graph_max_keywords": GRAPH_MAX_KEYWORDS,
            "graph_min_keyword_degree": MIN_KEYWORD_DEGREE,
            "graph_forget_threshold": GRAPH_FORGET_THRESHOLD,
            "feed_days": EXPORT_WINDOW_DAYS,
            "feed_max_items": EXPORT_MAX_ITEMS,
            "daily_ingest_limit": DAILY_INGEST_LIMIT,
            "db_retention_days": DB_RETENTION_DAYS,
            # 本轮实际发生的事：候选 / 入图 / 被遗忘，用于核对策略真的生效
            "graph_candidates": len(recent),
            "graph_news_used": len(kept),
            "graph_news_forgotten": len(recent) - len(kept),
            "graph_keywords_used": len(graph["nodes"]) - len(kept),
            "graph_keywords_forgotten": gstats["keywords_forgotten"],
            "graph_keywords_below_degree": gstats["keywords_below_degree"],
            "graph_keywords_below_strength": gstats["keywords_below_strength"],
            "pruned_this_run": pruned,
        },
        # 更新节奏作为数据导出，而不是写死在前端文案里。
        # 原因：调整定时策略后，前端文案若仍写旧时间就会与事实不符
        #（曾出现页面标注「每日 09:00」而实际为每 3 小时的情况）。
        "schedule": {
            "description": "每 3 小时自动更新",
            "trigger": (
                "由外部定时器（cron-job.org）按 cron `20 */3 * * *` 调用 GitHub Actions "
                "的 workflow_dispatch 接口触发采集与部署，无需打开网页、也无需保持电脑开机"
            ),
            "timezone": "Asia/Shanghai",
            "times_local": ["02:20", "05:20", "08:20", "11:20",
                            "14:20", "17:20", "20:20", "23:20"],
        },
    }
    digest = build_digest(rows, graph)
    os.makedirs(os.path.dirname(EXPORT_PATH), exist_ok=True)
    with open(EXPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "news": rows, "graph": graph, "digest": digest}, f, ensure_ascii=False)
    print(
        f"[export] 展示 {len(rows)} 条（库内归档 {total_db} 条）, "
        f"图谱 {len(graph['nodes'])} 节点 / {len(graph['links'])} 边 "
        f"（候选 {len(recent)} 条 → 入图 {len(kept)} 条，遗忘 {len(recent) - len(kept)} 条；"
        f"关键词 {gstats['keywords_total']} → {gstats['keywords_total'] - gstats['keywords_forgotten']} 个，"
        f"遗忘 {gstats['keywords_forgotten']} 个）"
        f" -> {EXPORT_PATH}"
    )


# ---------------------------------------------------------------- 主流程


def run(sources, only=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    run_at = parse_dt(datetime.now(timezone.utc))
    active = [s for s in sources if not only or s["id"] == only]

    # 本轮配额 = min(每轮均摊, 今日剩余)。两个约束缺一不可：
    #   均摊 —— 保证额度能铺满全天，否则第一轮就把 100 条用完，下午的新资讯挤不进来
    #   剩余 —— 保证一天总数不超过 DAILY_INGEST_LIMIT（手动触发额外跑也不会超额）
    per_run_target = -(-DAILY_INGEST_LIMIT // RUNS_PER_DAY)  # 向上取整
    used_today = ingested_today(conn)
    budget = max(0, min(per_run_target, DAILY_INGEST_LIMIT - used_today))
    if budget == 0:
        print(f"[quota] 今日已入库 {used_today} 条，达到每日上限 {DAILY_INGEST_LIMIT} 条，本轮只更新状态不写新数据")

    # 先全部抓取（采集与写入分离），失败来源单独记账，不影响其他源
    queues, results = {}, {}
    for src in active:
        status, message, fetched, items = "ok", "", 0, []
        try:
            items = FETCHERS[src["type"]](src)
            fetched = len(items)
        except Exception as e:  # 单源失败不影响其他源与已有数据
            status, message = "failed", f"{type(e).__name__}: {e}"
        queues[src["id"]] = items
        results[src["id"]] = {
            "status": status, "message": message, "fetched": fetched, "inserted": 0, "quota_cut": False
        }

    # 轮转写入：每轮每个来源取一条，配额用尽即停。
    # 若按来源顺序依次写满配额，排在前面的大流量源（HN）会吃光全天额度；
    # 轮转让四个来源都有机会入选，且「重复条目」不消耗配额（INSERT OR IGNORE 未写入才扣减）。
    cursors = {sid: 0 for sid in queues}
    drained = {sid: False for sid in queues}
    writable = [s["id"] for s in active if results[s["id"]]["status"] == "ok"]
    while budget > 0 and any(not drained[s] for s in writable):
        for sid in writable:
            if budget <= 0:
                break
            if drained[sid]:
                continue
            items = queues[sid]
            while cursors[sid] < len(items):
                item = items[cursors[sid]]
                cursors[sid] += 1
                if upsert_items(conn, [item]):
                    results[sid]["inserted"] += 1
                    budget -= 1
                    break
            if cursors[sid] >= len(items):
                drained[sid] = True
    for sid in writable:
        results[sid]["quota_cut"] = cursors[sid] < len(queues[sid])

    for src in active:
        r = results[src["id"]]
        status, message = r["status"], r["message"]
        skipped = len(queues[src["id"]]) - cursors[src["id"]]
        if status == "ok":
            if r["fetched"] == 0:
                status, message = "no_new", "来源返回 0 条"
            elif r["inserted"] == 0:
                status = "no_new"  # 有抓取但无新增：与抓取失败明确区分
                message = (
                    f"本轮配额已用尽（每日上限 {DAILY_INGEST_LIMIT} 条），剩余 {skipped} 条待下轮"
                    if r["quota_cut"]
                    else "抓取到的条目均已收录"
                )
            elif r["quota_cut"]:
                message = f"达到本轮配额，剩余 {skipped} 条顺延到下轮"
        conn.execute(
            "INSERT INTO update_runs (run_at, source_id, status, fetched, inserted, message) VALUES (?,?,?,?,?,?)",
            (run_at, src["id"], status, r["fetched"], r["inserted"], message[:300]),
        )
        conn.commit()
        print(f"[{src['id']}] {status}: fetched={r['fetched']} inserted={r['inserted']} {message}")

    pruned = prune_old(conn)
    if pruned:
        print(f"[retention] 已遗忘 {pruned} 条超过 {DB_RETENTION_DAYS} 天的记录，并回收空间")

    warn_if_stale(conn)
    export_json(conn, pruned=pruned)
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只采集指定来源 id")
    ap.add_argument("--fail-source", help="测试用：强制指定来源失败（注入坏 URL）")
    ap.add_argument("--export-only", action="store_true",
                    help="不联网采集，只用库内已有数据重算 data.json（本地验证遗忘策略用）")
    args = ap.parse_args()

    if args.export_only:
        _conn = sqlite3.connect(DB_PATH)
        _conn.row_factory = sqlite3.Row
        init_db(_conn)
        warn_if_stale(_conn)
        export_json(_conn, pruned=prune_old(_conn))
        _conn.close()
        sys.exit(0)

    sources = SOURCES
    if args.fail_source:
        for s in sources:
            if s["id"] == args.fail_source:
                s["url"] = "https://invalid.example.com/feed.xml"
    run(sources, only=args.only)
