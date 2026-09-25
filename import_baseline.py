#!/usr/bin/env python3
"""从线上 data.json 导入基线数据到本地 SQLite

为什么不用 fetch.py 重跑：
  Algolia search_by_date 只返回最新 40 条，历史数据抓不回来。
  线上 data.json 已含全部记录，直接解析导入是唯一方式。

用法：
  python import_baseline.py [path_to_data.json]
  默认从线上 URL 下载，也可指定本地文件路径。
"""

import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "news.db")
ONLINE_URL = "https://chuanyu-fangyuan.github.io/-aii-/data.json"

TRACKING_PARAMS = re.compile(
    r"^(utm_|fbclid$|gclid$|ref$|ref_src$|spm$|mc_cid$|mc_eid$)", re.I
)


def canonical_url(url: str) -> str:
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
    t = re.sub(r"[^\w一-鿿]+", " ", (title or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]


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
            published_at TEXT,
            published_unknown INTEGER NOT NULL DEFAULT 0,
            fetched_at TEXT NOT NULL,
            UNIQUE(title_hash, source_id)
        );
        CREATE TABLE IF NOT EXISTS update_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT NOT NULL,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL,
            fetched INTEGER DEFAULT 0,
            inserted INTEGER DEFAULT 0,
            message TEXT DEFAULT ''
        );
        """
    )


def load_json(source: str) -> dict:
    if source.startswith("http"):
        print(f"[download] 从 {source} 下载 data.json ...")
        req = urllib.request.Request(source, headers={"User-Agent": "ai-daily-brief/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"[download] 完成，{len(data.get('news', []))} 条新闻")
        return data
    else:
        with open(source, "r", encoding="utf-8") as f:
            return json.load(f)


def import_items(conn: sqlite3.Connection, news_items: list) -> tuple:
    inserted, skipped = 0, 0
    for item in news_items:
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not title or not url:
            skipped += 1
            continue

        summary = item.get("summary") or ""
        if summary:
            summary = re.sub(r"<[^>]+>", "", summary)
            summary = html.unescape(summary).strip()
            if len(summary) > 200:
                summary = summary[:197] + "..."

        published_at = item.get("published_at")
        fetched_at = item.get("fetched_at") or ""

        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO news
                   (url_hash, title_hash, title, url, summary, source_id,
                    source_name, published_at, published_unknown, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    url_hash(url),
                    title_hash(title),
                    title,
                    url,
                    summary,
                    item.get("source_id", "unknown"),
                    item.get("source_name", "Unknown"),
                    published_at,
                    0 if published_at else 1,
                    fetched_at,
                ),
            )
            inserted += cur.rowcount
        except sqlite3.Error as e:
            print(f"[warn] 插入失败: {e}")
            skipped += 1

    return inserted, skipped


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else ONLINE_URL

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    data = load_json(source)
    news_items = data.get("news", [])
    if not news_items:
        print("[error] data.json 中没有 news 数据")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    print(f"[import] 开始导入 {len(news_items)} 条新闻到 {DB_PATH}")
    inserted, skipped = import_items(conn, news_items)
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    sources = conn.execute(
        "SELECT source_id, COUNT(*) as cnt FROM news GROUP BY source_id"
    ).fetchall()

    print("\n[done] 导入完成:")
    print(f"  新增: {inserted}")
    print(f"  跳过(重复/无效): {skipped}")
    print(f"  库内总计: {total}")
    print("  源分布:")
    for s in sources:
        print(f"    {s['source_id']}: {s['cnt']} 条")

    conn.close()


if __name__ == "__main__":
    main()
