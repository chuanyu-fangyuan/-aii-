"""API Key 鉴权测试"""

import asyncio
import os
import sys
from unittest.mock import mock_open

import pytest
from fastapi import HTTPException

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import api.middleware as mw  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class TestGetApiKey:
    def test_reads_from_environment(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "env-key")
        assert mw.get_api_key() == "env-key"

    def test_returns_empty_when_not_configured(self, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setattr(mw.os.path, "exists", lambda _p: False)
        assert mw.get_api_key() == ""

    def test_falls_back_to_dotenv_file(self, monkeypatch):
        """环境变量没配时读 .env —— 本地开发不导出变量也能用"""
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setattr(mw.os.path, "exists", lambda _p: True)
        monkeypatch.setattr("builtins.open", mock_open(read_data="OTHER=1\nAPI_KEY=file-key\n"))

        assert mw.get_api_key() == "file-key"

    def test_dotenv_without_api_key_yields_empty(self, monkeypatch):
        monkeypatch.delenv("API_KEY", raising=False)
        monkeypatch.setattr(mw.os.path, "exists", lambda _p: True)
        monkeypatch.setattr("builtins.open", mock_open(read_data="DEEPSEEK_API_KEY=sk-x\n"))

        assert mw.get_api_key() == ""


class TestVerifyApiKey:
    def test_dev_mode_when_unconfigured(self, monkeypatch):
        monkeypatch.setattr(mw, "get_api_key", lambda: "")
        assert run(mw.verify_api_key(None)) == "dev-mode"

    def test_placeholder_value_is_treated_as_unconfigured(self, monkeypatch):
        """文档/模板里留的 your-api-key-here 不该被当成真钥匙，否则演示环境全 401"""
        monkeypatch.setattr(mw, "get_api_key", lambda: "your-api-key-here")
        assert run(mw.verify_api_key(None)) == "dev-mode"

    def test_missing_header_rejected(self, monkeypatch):
        monkeypatch.setattr(mw, "get_api_key", lambda: "real-key")
        with pytest.raises(HTTPException) as exc:
            run(mw.verify_api_key(None))
        assert exc.value.status_code == 401

    def test_wrong_key_rejected(self, monkeypatch):
        monkeypatch.setattr(mw, "get_api_key", lambda: "real-key")
        with pytest.raises(HTTPException) as exc:
            run(mw.verify_api_key("bad-key"))
        assert exc.value.status_code == 403

    def test_correct_key_accepted(self, monkeypatch):
        monkeypatch.setattr(mw, "get_api_key", lambda: "real-key")
        assert run(mw.verify_api_key("real-key")) == "real-key"

    def test_health_and_docs_are_public(self):
        # 探活与文档必须免鉴权，否则监控和本地调试都会被 401 挡住
        assert {"/health", "/docs"} <= mw.PUBLIC_PATHS
