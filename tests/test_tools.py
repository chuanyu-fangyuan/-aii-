"""Agent 工具层单元测试"""

import json
import os
import sys
import pytest

# 确保项目根目录在 path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from agent.tools import search_news, fetch_source, dedup_check, verify_claim, write_report


class TestSearchNews:
    def test_basic_search(self):
        result = search_news.invoke({"query": "AI", "top_k": 3})
        data = json.loads(result)
        assert "results" in data
        assert data["count"] >= 0

    def test_empty_query(self):
        result = search_news.invoke({"query": "", "top_k": 3})
        data = json.loads(result)
        # 空查询可能返回结果或错误
        assert "results" in data or "error" in data

    def test_chinese_query(self):
        result = search_news.invoke({"query": "人工智能", "top_k": 2})
        data = json.loads(result)
        assert "results" in data


class TestFetchSource:
    def test_valid_source(self):
        result = fetch_source.invoke({"source_id": "hackernews", "days": 7, "limit": 5})
        data = json.loads(result)
        assert "results" in data
        assert data["source"] == "hackernews"

    def test_invalid_source(self):
        result = fetch_source.invoke({"source_id": "invalid", "days": 7, "limit": 5})
        data = json.loads(result)
        assert "error" in data

    def test_all_sources(self):
        sources = ["hackernews", "techcrunch", "theverge", "arxiv"]
        for src in sources:
            result = fetch_source.invoke({"source_id": src, "days": 30, "limit": 3})
            data = json.loads(result)
            assert data["source"] == src


class TestDedupCheck:
    def test_nonexistent_url(self):
        result = dedup_check.invoke({"url": "https://example.com/nonexistent-ai-news"})
        data = json.loads(result)
        assert "exists" in data

    def test_empty_url(self):
        result = dedup_check.invoke({"url": ""})
        data = json.loads(result)
        assert "exists" in data


class TestVerifyClaim:
    def test_basic_claim(self):
        # 注意：此测试需要 DEEPSEEK_API_KEY
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            pytest.skip("DEEPSEEK_API_KEY 未设置")

        result = verify_claim.invoke({
            "claim": "OpenAI 发布了 GPT-5",
            "news_ids": []
        })
        data = json.loads(result)
        assert "verdict" in data or "raw_response" in data or "error" in data


class TestWriteReport:
    def test_basic_report(self):
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            pytest.skip("DEEPSEEK_API_KEY 未设置")

        result = write_report.invoke({"topics": "AI 芯片", "max_words": 500})
        data = json.loads(result)
        assert "report" in data or "error" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
