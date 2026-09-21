"""API Key 鉴权中间件"""

import os
from fastapi import Request, HTTPException
from fastapi.security import APIKeyHeader
from fastapi import Security

# 不需要鉴权的端点
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

# API Key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key() -> str:
    """从环境变量获取期望的 API Key"""
    key = os.environ.get("API_KEY", "")
    if not key:
        # 尝试从 .env 读取
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
    return key


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """验证 API Key"""
    expected = get_api_key()

    # 未配置 API Key 时，允许所有请求（开发模式）
    if not expected or expected == "your-api-key-here":
        return "dev-mode"

    if not api_key:
        raise HTTPException(status_code=401, detail="缺少 API Key，请在 Header 中提供 X-API-Key")

    if api_key != expected:
        raise HTTPException(status_code=403, detail="API Key 无效")

    return api_key
