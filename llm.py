"""统一 LLM 调用入口 + 成本埋点（Day 25）

为什么要有这一层：
    在它之前，仓库里散着 5 处各自 `requests.post` 到 DeepSeek 的代码
    （analyze 分类、/ask 问答、insight 洞察、agent 的两个工具），
    只有 analyze 一处会写 `llm_traces`。结果是：
      · 成本看板只能看到分类链路的钱，问答/Agent 的消耗全是黑洞；
      · 每处重写一遍重试、超时、错误分类，口径还各不相同。
    所以把「发请求 → 计量 → 落 trace」收成一个入口，调用方只关心语义。

计量口径（详见 db.py 注释）：
    · token 数取响应里的 usage（区分缓存命中/未命中，两档价差 50 倍）；
    · 单价按官方峰谷时段自动选择；
    · 汇率折算写死在 db.USD_CNY，只用于展示估算值。

用法：
    from llm import chat

    out = chat([{"role": "user", "content": prompt}], purpose="ask")
    if out["ok"]:
        answer = out["content"]
"""

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from db import (  # noqa: E402
    SQLITE_PATH,
    USD_CNY,
    calc_cost,
    estimate_cost_usd,
    is_peak_time,
)

DEFAULT_MODEL = "deepseek-chat"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# purpose 取值收口，避免各处自由发挥导致看板分成几十个维度
PURPOSES = ("analyze", "ask", "insight", "agent_verify", "agent_report", "eval", "agent")


# ============================================================
# API Key
# ============================================================

def get_api_key(explicit: str = "") -> str:
    """取 API Key：入参 > 环境变量 > .env 文件"""
    if explicit:
        return explicit
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key

    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return ""


# ============================================================
# 计量与埋点
# ============================================================

def parse_usage(usage: dict) -> dict:
    """从响应 usage 里抽出计费需要的字段。

    DeepSeek 会单独返回 prompt_cache_hit_tokens；没返回时（或非 DeepSeek 兼容端点）
    一律按「缓存未命中」计，宁可算贵也不算便宜。
    """
    usage = usage or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    return {
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
        "cache_hit_tokens": max(0, min(hit, prompt_tokens)),
    }


def _normalize_usage(usage: dict) -> dict:
    """既能吃原始 usage（prompt_tokens...），也能吃已归一化的 metrics"""
    if "input_tokens" in usage:
        return usage
    return parse_usage(usage)


def record_trace(
    purpose: str,
    model: str,
    usage: dict,
    latency_ms: int,
    status: str = "ok",
    news_id: int = None,
    conn: sqlite3.Connection = None,
    peak: bool = None,
) -> float:
    """写一条 llm_traces 并返回本次费用（元）"""
    metrics = _normalize_usage(usage)
    cost = calc_cost(
        metrics["input_tokens"],
        metrics["output_tokens"],
        metrics.get("cache_hit_tokens", 0),
        peak=peak,
    )

    own_conn = conn is None
    conn = conn or sqlite3.connect(SQLITE_PATH)
    try:
        conn.execute(
            """INSERT INTO llm_traces
               (model, purpose, input_tokens, output_tokens, latency_ms, cost_yuan, status, news_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model,
                purpose,
                metrics["input_tokens"],
                metrics["output_tokens"],
                int(latency_ms),
                cost,
                status,
                news_id,
            ),
        )
        conn.commit()
    finally:
        if own_conn:
            conn.close()
    return cost


# ============================================================
# 调用入口
# ============================================================

def chat(
    messages: list,
    purpose: str = "ask",
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 800,
    json_mode: bool = False,
    timeout: int = 60,
    api_key: str = "",
    news_id: int = None,
) -> dict:
    """调用 DeepSeek 并自动埋点。

    返回统一结构：
      成功 {"ok": True, "content": str, "usage": {...}, "latency_ms": int, "cost_yuan": float}
      失败 {"ok": False, "error_type": str, "error_message": str, "latency_ms": int}
    失败也会落 trace（status='error'），否则「调用了但没花钱」这类黑洞统计不到。
    """
    key = get_api_key(api_key)
    if not key:
        return {
            "ok": False,
            "error_type": "no_api_key",
            "error_message": "未配置 DEEPSEEK_API_KEY",
            "latency_ms": 0,
        }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )

    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        latency = int((time.time() - started) * 1000)
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:  # pragma: no cover - 读不到就算了
            pass
        record_trace(purpose, model, {}, latency, "error", news_id)
        return {
            "ok": False,
            "error_type": "api_error",
            "error_message": f"HTTP {exc.code}: {detail}",
            "latency_ms": latency,
        }
    except json.JSONDecodeError as exc:
        latency = int((time.time() - started) * 1000)
        record_trace(purpose, model, {}, latency, "error", news_id)
        return {
            "ok": False,
            "error_type": "json_parse",
            "error_message": f"响应不是合法 JSON: {str(exc)[:100]}",
            "latency_ms": latency,
        }
    except Exception as exc:
        latency = int((time.time() - started) * 1000)
        msg = str(exc).lower()
        is_timeout = isinstance(exc, TimeoutError) or "timeout" in msg or "timed out" in msg
        record_trace(purpose, model, {}, latency, "error", news_id)
        return {
            "ok": False,
            "error_type": "timeout" if is_timeout else "unknown",
            "error_message": str(exc)[:200],
            "latency_ms": latency,
        }

    latency = int((time.time() - started) * 1000)
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        record_trace(purpose, model, {}, latency, "error", news_id)
        return {
            "ok": False,
            "error_type": "bad_response",
            "error_message": "响应缺少 choices[0].message.content",
            "latency_ms": latency,
        }

    usage = body.get("usage", {})
    metrics = parse_usage(usage)
    cost = record_trace(purpose, model, metrics, latency, "ok", news_id)

    return {
        "ok": True,
        "content": content,
        "usage": metrics,
        "latency_ms": latency,
        "cost_yuan": cost,
    }


# ============================================================
# LangChain 回调（Agent 走 langchain，不能复用上面的 urllib 路径）
# ============================================================

def _make_langchain_handler():
    """延迟导入：没装 langchain 的环境（如只跑 API 的容器）不该因此报错"""
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except ImportError:  # pragma: no cover - 依赖缺失时的降级
        return None

    class TraceHandler(BaseCallbackHandler):
        """把 langchain 的 token 用量写进 llm_traces"""

        def __init__(self, purpose: str = "agent"):
            self.purpose = purpose

        def on_llm_end(self, response, **kwargs):
            usage = {}
            try:
                msg = response.generations[0][0].message
                usage = getattr(msg, "usage_metadata", None) or {}
            except (IndexError, AttributeError):
                usage = {}

            metrics = {
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                # langchain 的 usage_metadata 会把命中缓存的部分单列在 input_token_details
                "cache_hit_tokens": int(
                    (usage.get("input_token_details") or {}).get("cache_read") or 0
                ),
            }
            try:
                record_trace(self.purpose, DEFAULT_MODEL, metrics, 0, "ok")
            except Exception:  # pragma: no cover - 埋点失败不能影响主流程
                pass

        def on_llm_error(self, error, **kwargs):
            try:
                record_trace(self.purpose, DEFAULT_MODEL, {}, 0, "error")
            except Exception:  # pragma: no cover
                pass

    return TraceHandler


_langchain_handler_cls = _make_langchain_handler()


def langchain_callbacks(purpose: str = "agent"):
    """给 ChatOpenAI(callbacks=...) 用的回调列表；依赖缺失时返回空列表"""
    if _langchain_handler_cls is None:
        return []
    return [_langchain_handler_cls(purpose=purpose)]


# ============================================================
# 成本看板数据
# ============================================================

def stats(days: int = None, conn: sqlite3.Connection = None) -> dict:
    """汇总 llm_traces：总量、按用途分布、按日趋势。

    同时给 /api/stats（JSON 接口）与 web/stats.json（静态站展示）复用，
    避免两处各写一套 SQL 导致口径不一致。
    """
    own_conn = conn is None
    conn = conn or sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        where, params = "", []
        if days:
            where = "WHERE created_at >= datetime('now', ?)"
            params = [f"-{int(days)} days"]

        row = conn.execute(
            f"""SELECT COUNT(*) AS calls,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(cost_yuan), 0) AS cost_yuan,
                       SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END) AS error_calls
                FROM llm_traces {where}""",
            params,
        ).fetchone()

        by_purpose = [
            dict(r)
            for r in conn.execute(
                f"""SELECT purpose, COUNT(*) AS calls,
                           COALESCE(SUM(input_tokens), 0) AS input_tokens,
                           COALESCE(SUM(output_tokens), 0) AS output_tokens,
                           COALESCE(SUM(cost_yuan), 0) AS cost_yuan
                    FROM llm_traces {where}
                    GROUP BY purpose ORDER BY cost_yuan DESC""",
                params,
            )
        ]

        daily = [
            dict(r)
            for r in conn.execute(
                """SELECT date(created_at) AS day, COUNT(*) AS calls,
                          COALESCE(SUM(cost_yuan), 0) AS cost_yuan
                   FROM llm_traces
                   WHERE created_at >= datetime('now', '-14 days')
                   GROUP BY day ORDER BY day DESC""",
            )
        ]
    finally:
        if own_conn:
            conn.close()

    calls = row["calls"] or 0
    cost = row["cost_yuan"] or 0
    return {
        "calls": calls,
        "input_tokens": row["input_tokens"] or 0,
        "output_tokens": row["output_tokens"] or 0,
        "cost_yuan": round(cost, 6),
        "error_calls": row["error_calls"] or 0,
        "avg_cost_per_call_yuan": round(cost / calls, 6) if calls else 0.0,
        "by_purpose": by_purpose,
        "daily": daily,
        "estimated": True,  # 提示：按官方价目表估算，非账单
        "peak_now": is_peak_time(),
        "unit_note": "按 DeepSeek 官方价目表估算（含峰谷与缓存价），实际以账户账单为准",
    }


# ============================================================
# 与账单对账
# ============================================================

def reconcile(actual_yuan: float, days: int = None, conn: sqlite3.Connection = None) -> dict:
    """把控制台账单与本地估算对齐。

    估算永远只是估算（汇率、峰谷边界、未埋点链路都会造成偏差）。
    这个方法给出「账单 / 估算」的比值，让偏差一眼可见而不是靠感觉。

    注意：比值明显偏离 1 时，**先查埋点覆盖率再看单价** ——
    首次对账就是这么发现「控制台 255 次调用，本地只能解释 32 次」的
    （当时评测链路还没有埋点，控制台的钱有一大半本地看不见）。
    """
    est = stats(days=days, conn=conn)
    estimated = est["cost_yuan"]
    ratio = (actual_yuan / estimated) if estimated else None

    if ratio is None:
        verdict = "本地没有该时段记录，无法比较"
    elif 0.9 <= ratio <= 1.1:
        verdict = "估算与账单一致（偏差 < 10%）"
    elif ratio > 1.1:
        verdict = "账单高于估算：先查是否有未埋点的调用，再看峰谷判断"
    else:
        verdict = "估算高于账单：先查峰谷时段判断与缓存命中价是否用对"

    return {
        "window_days": days or 0,
        "estimated_yuan": round(estimated, 6),
        "actual_yuan": round(actual_yuan, 6),
        "ratio": round(ratio, 3) if ratio else None,
        "local_calls": est["calls"],
        "local_tokens": est["input_tokens"] + est["output_tokens"],
        "by_purpose": est["by_purpose"],
        "verdict": verdict,
    }


# ============================================================
# 一次性：按新价目重算历史 trace
# ============================================================

def recost_traces(conn: sqlite3.Connection = None) -> int:
    """按当前价目表重算历史 cost_yuan 并写回。

    为什么需要：量纲修好之前，历史行是按错误公式（少算 1000 倍）写的。
    历史行没有记录缓存命中量，一律按「缓存未命中」重算（算贵不算便宜）。
    峰谷按记录时刻判断，取不到时间就用非峰值。
    """
    own_conn = conn is None
    conn = conn or sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    updated = 0
    try:
        rows = conn.execute(
            "SELECT id, input_tokens, output_tokens, created_at FROM llm_traces"
        ).fetchall()
        for r in rows:
            peak = None
            if r["created_at"]:
                try:
                    peak = is_peak_time(datetime.fromisoformat(r["created_at"]).replace(tzinfo=timezone.utc))
                except ValueError:  # pragma: no cover - 时间格式异常时退回非峰值
                    peak = False
            cost = estimate_cost_usd(r["input_tokens"] or 0, r["output_tokens"] or 0, 0, peak) * USD_CNY
            conn.execute("UPDATE llm_traces SET cost_yuan = ? WHERE id = ?", (cost, r["id"]))
            updated += 1
        conn.commit()
    finally:
        if own_conn:
            conn.close()
    return updated


if __name__ == "__main__":  # pragma: no cover - 手工运维入口
    if "--recost" in sys.argv:
        print(f"已按新价目重算 {recost_traces()} 条历史 trace")
    elif "--reconcile" in sys.argv:
        # 用法：python llm.py --reconcile 0.39 --days 1
        idx = sys.argv.index("--reconcile")
        actual = float(sys.argv[idx + 1])
        days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else None
        print(json.dumps(reconcile(actual, days=days), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
