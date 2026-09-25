"""fetch.py 单元测试"""

import os
import sys
import pytest
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from fetch import (
    canonical_url,
    title_hash,
    url_hash,
    parse_dt,
)


class TestCanonicalUrl:
    def test_basic_url(self):
        url = "https://example.com/path?utm_source=test"
        result = canonical_url(url)
        assert "utm_source" not in result
        assert "example.com" in result

    def test_empty_url(self):
        assert canonical_url("") == ""

    def test_url_with_tracking_params(self):
        url = "https://example.com/page?fbclid=123&utm_medium=social"
        result = canonical_url(url)
        assert "fbclid" not in result
        assert "utm_medium" not in result

    def test_url_without_tracking(self):
        url = "https://example.com/page?id=123"
        result = canonical_url(url)
        assert "id=123" in result


class TestHashFunctions:
    def test_url_hash_consistency(self):
        url = "https://example.com/article"
        h1 = url_hash(url)
        h2 = url_hash(url)
        assert h1 == h2

    def test_title_hash_consistency(self):
        title = "AI News Article"
        h1 = title_hash(title)
        h2 = title_hash(title)
        assert h1 == h2

    def test_different_inputs_different_hashes(self):
        h1 = url_hash("https://example.com/a")
        h2 = url_hash("https://example.com/b")
        assert h1 != h2


class TestParseDt:
    def test_datetime_with_timezone(self):
        dt = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)
        result = parse_dt(dt)
        assert "2026-09-22" in result
        assert "12:00:00" in result

    def test_datetime_without_timezone(self):
        dt = datetime(2026, 9, 22, 12, 0, 0)
        result = parse_dt(dt)
        assert "2026-09-22" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
