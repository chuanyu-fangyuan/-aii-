#!/usr/bin/env python3
"""AI 分析流水线

对 news 表中 ai_status != 'done' 的记录调用 DeepSeek-V3 进行分析。
特性：
  - 噪声过滤：跳过 HN 低分帖子（score < 5）
  - 幂等：已处理记录不重复分析
  - 容错：单条失败不阻断，错误落 ai_errors
  - 节流：每 10 条 sleep 1s，防 429
  - 重试：指数退避（1s/2s/4s），最多 3 次
  - 成本追踪：每次调用记录 token 和费用到 llm_traces

用法：
  python analyze.py                    # 分析所有待处理记录
  python analyze.py --limit 10         # 只分析前 10 条
  python analyze.py --dry-run          # 只打印待分析列表，不实际调用
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from db import SQLITE_PATH, init_sqlite, calc_cost

# ---------------------------------------------------------------- 配置
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"  # DeepSeek-V3
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1  # 秒
THROTTLE_INTERVAL = 10  # 每 N 条暂停 1 秒
THROTTLE_DELAY = 1.0  # 暂停时长
HTTP_TIMEOUT = 60  # 秒
VALID_CATEGORIES = {"模型", "应用", "芯片硬件", "开源", "融资创业", "政策监管", "研究突破", "其他"}
VALID_VERIFICATIONS = {"confirmed", "unverified", "disputed"}

# ---------------------------------------------------------------- Prompt 模板
PROMPT_TEMPLATE_PATH = os.path.join(BASE_DIR, "prompts", "v1_baseline.txt")


def load_prompt() -> str:
    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def build_prompt(title: str, summary: str, source_name: str, published_at: str) -> str:
    template = load_prompt()
    return template.format(
        title=title or "",
        summary=summary or "",
        source_name=source_name or "",
        published_at=published_at or "未知",
    )


# ---------------------------------------------------------------- 数据库操作


def get_candidates_sql() -> str:
    """SQLite 版本的候选查询（含噪声过滤）"""
    return """
        SELECT id, title, summary, source_id, source_name, published_at
        FROM news
        WHERE COALESCE(published_at, fetched_at) >= datetime('now', '-7 days')
          AND (ai_status IS NULL OR ai_status != 'done')
          AND (
            source_id != 'hackernews'
            OR (
              summary LIKE '% 分%'
              AND COALESCE(
                CAST(
                  SUBSTR(
                    summary,
                    INSTR(summary, '·') + 2,
                    INSTR(SUBSTR(summary, INSTR(summary, '·') + 2), '分') - 1
                  ) AS INTEGER
                ), 0
              ) >= 5
            )
          )
        ORDER BY COALESCE(published_at, fetched_at) DESC
    """


def get_candidates(conn: sqlite3.Connection, limit: int = 0) -> list:
    sql = get_candidates_sql()
    if limit > 0:
        sql += f" LIMIT {limit}"
    return [dict(r) for r in conn.execute(sql).fetchall()]


def mark_analyzing(conn: sqlite3.Connection, news_id: int):
    conn.execute("UPDATE news SET ai_status = 'analyzing' WHERE id = ?", (news_id,))
    conn.commit()


def mark_done(conn: sqlite3.Connection, news_id: int, result: dict):
    conn.execute(
        """UPDATE news SET
             ai_category = ?,
             ai_summary_zh = ?,
             importance = ?,
             verification = ?,
             verification_note = ?,
             entities_json = ?,
             ai_status = 'done'
           WHERE id = ?""",
        (
            result.get("category", "其他"),
            result.get("summary_zh", ""),
            result.get("importance", 1),
            result.get("verification", "unverified"),
            result.get("verification_note", ""),
            json.dumps(result.get("entities", []), ensure_ascii=False),
            news_id,
        ),
    )
    conn.commit()


def mark_error(conn: sqlite3.Connection, news_id: int):
    conn.execute("UPDATE news SET ai_status = 'error' WHERE id = ?", (news_id,))
    conn.commit()


def log_error(conn: sqlite3.Connection, news_id: int, error_type: str, message: str, retry_count: int):
    conn.execute(
        """INSERT INTO ai_errors (news_id, error_type, error_message, retry_count)
           VALUES (?, ?, ?, ?)""",
        (news_id, error_type, message[:500], retry_count),
    )
    conn.commit()


def log_trace(conn: sqlite3.Connection, model: str, purpose: str,
              input_tokens: int, output_tokens: int, latency_ms: int,
              cost: float, status: str, news_id: int = None):
    conn.execute(
        """INSERT INTO llm_traces
           (model, purpose, input_tokens, output_tokens, latency_ms, cost_yuan, status, news_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (model, purpose, input_tokens, output_tokens, latency_ms, cost, status, news_id),
    )
    conn.commit()


# ---------------------------------------------------------------- DeepSeek API


def call_deepseek(prompt: str, api_key: str) -> dict:
    """调用 DeepSeek API，返回解析后的 JSON 结果。

    返回: {
      "ok": True/False,
      "result": {...},  # 成功时
      "error_type": str,  # 失败时
      "error_message": str,
      "input_tokens": int,
      "output_tokens": int,
      "latency_ms": int,
    }
    """
    import urllib.request

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个专业的 AI 行业资讯分析师，只输出合法 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},  # 强制 JSON 输出
        "temperature": 0.1,
        "max_tokens": 500,
    }).encode("utf-8")

    req = urllib.request.Request(DEEPSEEK_API_URL, data=payload, headers=headers)
    start = time.time()

    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        latency = int((time.time() - start) * 1000)

        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        # 解析 JSON
        result = json.loads(content)
        return {
            "ok": True,
            "result": result,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency,
        }

    except urllib.error.HTTPError as e:
        latency = int((time.time() - start) * 1000)
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return {
            "ok": False,
            "error_type": "api_error",
            "error_message": f"HTTP {e.code}: {body}",
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": latency,
        }

    except json.JSONDecodeError as e:
        latency = int((time.time() - start) * 1000)
        return {
            "ok": False,
            "error_type": "json_parse",
            "error_message": f"LLM 返回非 JSON: {str(e)[:100]}",
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": latency,
        }

    except Exception as e:
        latency = int((time.time() - start) * 1000)
        error_type = "timeout" if "timeout" in str(e).lower() else "unknown"
        return {
            "ok": False,
            "error_type": error_type,
            "error_message": str(e)[:200],
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": latency,
        }


def validate_result(result: dict) -> dict:
    """校验并修正 LLM 返回的字段"""
    # 分类校验
    cat = result.get("category", "其他")
    if cat not in VALID_CATEGORIES:
        result["category"] = "其他"

    # 重要性校验
    imp = result.get("importance", 1)
    if not isinstance(imp, int) or imp < 1 or imp > 5:
        try:
            imp = max(1, min(5, int(imp)))
        except (TypeError, ValueError):
            imp = 1
    result["importance"] = imp

    # 可信度校验
    ver = result.get("verification", "unverified")
    if ver not in VALID_VERIFICATIONS:
        result["verification"] = "unverified"

    # 实体列表
    entities = result.get("entities", [])
    if not isinstance(entities, list):
        entities = []
    result["entities"] = entities[:5]

    # 摘要
    summary_zh = result.get("summary_zh", "")
    if not isinstance(summary_zh, str) or not summary_zh.strip():
        result["summary_zh"] = result.get("title", "")[:100]

    return result


def analyze_one(news_item: dict, api_key: str) -> dict:
    """分析单条新闻，带重试"""
    prompt = build_prompt(
        news_item["title"],
        news_item.get("summary", ""),
        news_item.get("source_name", ""),
        news_item.get("published_at", ""),
    )

    last_result = None
    for attempt in range(MAX_RETRIES):
        result = call_deepseek(prompt, api_key)
        last_result = result

        if result["ok"]:
            validated = validate_result(result["result"])
            return {
                "success": True,
                "result": validated,
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
                "latency_ms": result["latency_ms"],
                "retries": attempt,
            }

        # 不可重试的错误（如 JSON 格式问题，换 prompt 也没用）
        if result["error_type"] == "json_parse" and attempt >= 1:
            break

        # 指数退避
        if attempt < MAX_RETRIES - 1:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            time.sleep(delay)

    return {
        "success": False,
        "error_type": last_result.get("error_type", "unknown"),
        "error_message": last_result.get("error_message", ""),
        "input_tokens": last_result.get("input_tokens", 0),
        "output_tokens": last_result.get("output_tokens", 0),
        "latency_ms": last_result.get("latency_ms", 0),
        "retries": MAX_RETRIES - 1,
    }


# ---------------------------------------------------------------- 主流程


def run_analysis(limit: int = 0, dry_run: bool = False):
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    init_sqlite(conn)

    candidates = get_candidates(conn, limit=limit)
    print(f"[analyze] 待分析: {len(candidates)} 条")

    if dry_run:
        for c in candidates[:10]:
            print(f"  #{c['id']} [{c['source_id']}] {c['title'][:60]}")
        if len(candidates) > 10:
            print(f"  ... 还有 {len(candidates) - 10} 条")
        conn.close()
        return

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        # 尝试从 .env 读取
        env_path = os.path.join(BASE_DIR, ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("DEEPSEEK_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
    if not api_key or api_key == "sk-xxxx":
        print("[error] 未设置 DEEPSEEK_API_KEY，请在 .env 或环境变量中配置")
        conn.close()
        sys.exit(1)

    success_count = 0
    error_count = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0

    for i, item in enumerate(candidates):
        news_id = item["id"]
        title_short = (item["title"] or "")[:50]

        # 标记为分析中
        mark_analyzing(conn, news_id)

        # 执行分析
        result = analyze_one(item, api_key)

        if result["success"]:
            mark_done(conn, news_id, result["result"])
            success_count += 1
            status = "ok"
            print(f"  [{i+1}/{len(candidates)}] ✓ #{news_id} {title_short}")
        else:
            mark_error(conn, news_id)
            log_error(conn, news_id, result["error_type"], result["error_message"], result["retries"])
            error_count += 1
            status = "error"
            print(f"  [{i+1}/{len(candidates)}] ✗ #{news_id} {title_short} → {result['error_type']}")

        # 记录 trace
        inp_tok = result.get("input_tokens", 0)
        out_tok = result.get("output_tokens", 0)
        cost = calc_cost(inp_tok, out_tok)
        log_trace(
            conn, DEEPSEEK_MODEL, "analyze",
            inp_tok, out_tok, result.get("latency_ms", 0),
            cost, status, news_id,
        )
        total_input_tokens += inp_tok
        total_output_tokens += out_tok
        total_cost += cost

        # 节流
        if (i + 1) % THROTTLE_INTERVAL == 0:
            print(f"  [throttle] 已处理 {i+1} 条，暂停 {THROTTLE_DELAY}s")
            time.sleep(THROTTLE_DELAY)

    # 汇总
    print(f"\n[done] 分析完成:")
    print(f"  成功: {success_count}")
    print(f"  失败: {error_count}")
    print(f"  总 token: 输入 {total_input_tokens} + 输出 {total_output_tokens}")
    print(f"  预估成本: ¥{total_cost:.4f}")

    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只分析前 N 条")
    ap.add_argument("--dry-run", action="store_true", help="只打印待分析列表")
    args = ap.parse_args()
    run_analysis(limit=args.limit, dry_run=args.dry_run)
