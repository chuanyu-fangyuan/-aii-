"""今日 AI 洞察生成器

从当日新闻中提取 3-5 个主题，生成洞察摘要。
结果写入 data/insight.json，前端读取展示。
"""

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_PATH = os.path.join(BASE_DIR, "data", "news.db")
INSIGHT_PATH = os.path.join(BASE_DIR, "data", "insight.json")

PROMPT_PATH = os.path.join(BASE_DIR, "prompts", "insight_v1.txt")


def get_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_today_news(conn, days: int = 1):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT id, title, ai_category, ai_summary_zh, source_name
           FROM news
           WHERE ai_status = 'done'
             AND COALESCE(published_at, fetched_at) >= ?
           ORDER BY importance DESC, published_at DESC
           LIMIT 50""",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def build_news_digest(news):
    parts = []
    for i, n in enumerate(news, 1):
        # 无分类时不留下多余空格（原写法在无分类行会拼出 "2.  标题" 两个空格）
        cat = f"[{n['ai_category']}] " if n.get("ai_category") else ""
        summary = n.get("ai_summary_zh") or n["title"]
        parts.append(f"{i}. {cat}{summary[:100]}")
    return "\n".join(parts)


def generate_insight(api_key: str, news: list) -> dict:
    """生成今日洞察。请求与计量都交给统一入口 llm.chat（purpose='insight'）"""
    from llm import chat

    digest = build_news_digest(news)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        template = f.read()

    prompt = template.replace("{date}", today).replace("{news_digest}", digest)

    out = chat(
        [{"role": "user", "content": prompt}],
        purpose="insight",
        temperature=0.5,
        max_tokens=1000,
        json_mode=True,
        timeout=60,
        api_key=api_key,
    )
    if not out["ok"]:
        raise RuntimeError(f"洞察生成失败: {out['error_message']}")
    return json.loads(out["content"])


def save_insight(data: dict):
    os.makedirs(os.path.dirname(INSIGHT_PATH), exist_ok=True)
    with open(INSIGHT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_insight():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE_DIR, ".env"))
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    if not api_key:
        print("[insight] 未配置 DEEPSEEK_API_KEY，跳过")
        return

    conn = get_conn()
    news = get_today_news(conn)
    conn.close()

    if len(news) < 3:
        print(f"[insight] 今日新闻不足 3 条（{len(news)}），跳过")
        return

    print(f"[insight] 基于 {len(news)} 条新闻生成洞察...")
    result = generate_insight(api_key, news)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "news_count": len(news),
        "topics": result.get("topics", []),
        "summary": result.get("summary", ""),
    }

    save_insight(output)
    print(f"[insight] 完成: {len(output['topics'])} 个主题, 保存到 {INSIGHT_PATH}")


if __name__ == "__main__":
    run_insight()
