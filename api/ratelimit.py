"""公开演示的每日提问配额

为什么必须有：
    线上演示地址一旦公开，`/ask` 就是一个「任何人点一下都花你钱」的入口。
    没有配额时，一条被转发的链接就能把 DeepSeek 额度刷光，而且事后无法追责。
    所以公开端点必须自带闸门 —— 这不是性能优化，是成本安全。

设计取舍（都是有意为之，不是没做完）：
    · 计数放内存：Fly 上只有 1 台常驻机器，进程重启即清零。
      要跨实例/重启持久化就得引入 Redis 或往库里写 —— 为演示场景不值得，
      代价是「重启后配额重置」，已在 README 如实标注。
    · 按北京日期切分：与站点展示时区一致，用户看到的「今天」和计数口径相同。
    · 先判配额再判 Key：配额用尽时连「没配 Key」的请求也直接 429，
      避免配额判定被 Key 校验绕过。
    · 双闸门：单 IP 日配额（防个人刷）+ 全局日上限（防换 IP 刷）。
"""

import os
import threading
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

# 单 IP 每日提问上限（公开演示口径，可用环境变量覆盖）
PER_IP_DAILY = int(os.environ.get("ASK_DAILY_PER_IP", "5"))
# 全局每日上限：即使对方不停换 IP，也烧不穿这个数
GLOBAL_DAILY = int(os.environ.get("ASK_DAILY_GLOBAL", "100"))

SHANGHAI = timezone(timedelta(hours=8))


def quota_date(now: datetime = None) -> str:
    """配额归属日期（北京时间，与前端展示口径一致）"""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(SHANGHAI).strftime("%Y-%m-%d")


def client_ip(request: Request) -> str:
    """取真实客户端 IP。

    线上跑在 Fly 的反向代理后面，`request.client.host` 会是代理地址，
    真实来源在 `X-Forwarded-For` 的第一段（后续段是中间代理链）。
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class DailyQuota:
    """按 IP + 全局的每日计数（内存实现，线程安全）"""

    def __init__(self, per_ip: int = None, global_limit: int = None):
        self.per_ip = PER_IP_DAILY if per_ip is None else per_ip
        self.global_limit = GLOBAL_DAILY if global_limit is None else global_limit
        self._lock = threading.Lock()
        self._day = quota_date()
        self._per_ip = {}
        self._global = 0
        self._rejected = 0

    def _rollover_if_needed(self, now: datetime = None):
        today = quota_date(now)
        if today != self._day:
            self._day = today
            self._per_ip = {}
            self._global = 0
            self._rejected = 0

    def check_and_consume(self, ip: str, now: datetime = None) -> dict:
        """判定并占用一次配额。返回 {"allowed", "reason", "remaining"}"""
        with self._lock:
            self._rollover_if_needed(now)

            if self._global >= self.global_limit:
                self._rejected += 1
                return {"allowed": False, "reason": "global", "remaining": 0}

            used = self._per_ip.get(ip, 0)
            if used >= self.per_ip:
                self._rejected += 1
                return {"allowed": False, "reason": "per_ip", "remaining": 0}

            self._per_ip[ip] = used + 1
            self._global += 1
            return {
                "allowed": True,
                "reason": None,
                "remaining": self.per_ip - self._per_ip[ip],
            }

    def snapshot(self, ip: str = None, now: datetime = None) -> dict:
        with self._lock:
            self._rollover_if_needed(now)
            return {
                "date": self._day,
                "per_ip_limit": self.per_ip,
                "global_limit": self.global_limit,
                "global_used": self._global,
                "ip_used": self._per_ip.get(ip, 0) if ip else None,
                "ip_remaining": (self.per_ip - self._per_ip.get(ip, 0)) if ip else None,
                "rejected": self._rejected,
            }

    def reset(self):
        """仅供测试使用"""
        with self._lock:
            self._day = quota_date()
            self._per_ip = {}
            self._global = 0
            self._rejected = 0


_quota = DailyQuota()


def get_quota() -> DailyQuota:
    return _quota


def enforce(request: Request) -> dict:
    """在公开端点入口调用：超限直接 429，并给出人类可读的原因"""
    ip = client_ip(request)
    result = get_quota().check_and_consume(ip)

    if not result["allowed"]:
        if result["reason"] == "global":
            detail = (
                "今日全站提问额度已用完（公开演示的额度保护）。"
                "可以本地部署后继续使用：见 README「本地运行」。"
            )
        else:
            detail = (
                f"公开演示每个 IP 每天可提问 {get_quota().per_ip} 次，今天的额度已用完。"
                "明天恢复；本地部署后可不受此限制（见 README「本地运行」）。"
            )
        raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": "3600"})

    return result
