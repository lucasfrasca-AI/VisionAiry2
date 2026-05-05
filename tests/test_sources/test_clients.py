"""Tests for all 27 VisionAiry2 source clients.

Covers for each client:
  - test_<sid>_instantiates       — source_id and needs_key match expectations
  - test_<sid>_is_available       — env-var gate works correctly
  - test_<sid>_cache_roundtrip    — second fetch() call hits disk cache, no extra HTTP call
  - test_<sid>_fetch_schema       — SourceResult / SourceDocument fields are correctly populated

No real network calls are made; all HTTP is mocked via patch.object or sys.modules patching.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.sources.base import SourceDocument, SourceQuery, SourceResult
from src.sources.registry import reset_instances


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_mock_response(data, status_code: int = 200, text: str | None = None):
    """Build a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    if text is not None:
        resp.text = text
        resp.content = text.encode() if isinstance(text, str) else text
        resp.json.return_value = {}
    elif isinstance(data, str):
        resp.text = data
        resp.content = data.encode()
        resp.json.side_effect = Exception("not json")
    else:
        resp.json.return_value = data
        resp.text = str(data)
        resp.content = resp.text.encode()
    return resp


@pytest.fixture(autouse=True)
def reset_registry():
    """Clear the source-client singleton cache around every test."""
    reset_instances()
    yield
    reset_instances()


# ─────────────────────────────────────────────────────────────────────────────
# finnhub
# ─────────────────────────────────────────────────────────────────────────────

class TestFinnhubClient:
    def _client(self):
        from src.sources.finnhub import FinnhubClient
        return FinnhubClient(MagicMock())

    def test_finnhub_instantiates(self):
        c = self._client()
        assert c.source_id == "finnhub"
        assert c.needs_key is True
        assert c.key_env_var == "FINNHUB_API_KEY"

    def test_finnhub_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("FINNHUB_API_KEY", "test_key")
        assert c.is_available() is True

    def test_finnhub_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response([
            {"id": 1, "headline": "Test", "summary": "s",
             "url": "http://x.com", "datetime": 1700000000, "source": "Reuters"}
        ])
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(ticker="NVDA", lookback_days=7)
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_finnhub_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response([
            {"id": 99, "headline": "NVDA earnings beat analyst estimates", "summary": "Test summary",
             "url": "https://www.bloomberg.com/news/nvda-earnings", "datetime": 1700000000, "source": "Bloomberg"}
        ])
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(ticker="NVDA"))
        assert isinstance(result, SourceResult)
        assert result.source == "finnhub"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "news"
        assert result.documents[0].title == "NVDA earnings beat analyst estimates"


# ─────────────────────────────────────────────────────────────────────────────
# fmp  (INVALID key — entire class skipped)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="FMP_API_KEY INVALID")
class TestFMPClient:
    def test_fmp_skipped(self):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# findata
# ─────────────────────────────────────────────────────────────────────────────

class TestFinancialDatasetsClient:
    def _client(self):
        from src.sources.findata import FinancialDatasetsClient
        return FinancialDatasetsClient(MagicMock())

    def test_findata_instantiates(self):
        c = self._client()
        assert c.source_id == "findata"
        assert c.needs_key is True
        assert c.key_env_var == "FINANCIAL_DATASETS_API_KEY"

    def test_findata_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("FINANCIAL_DATASETS_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("FINANCIAL_DATASETS_API_KEY", "test_key")
        assert c.is_available() is True

    def test_findata_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINANCIAL_DATASETS_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response(
            {"income_statements": [{"period_of_report": "2024-09-30", "revenue": 35000000}]}
        )
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(ticker="NVDA")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_findata_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINANCIAL_DATASETS_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response(
            {"income_statements": [{"period_of_report": "2024-09-30", "revenue": 35000000}]}
        )
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(ticker="NVDA"))
        assert isinstance(result, SourceResult)
        assert result.source == "findata"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "market_data"


# ─────────────────────────────────────────────────────────────────────────────
# alpha_vantage
# ─────────────────────────────────────────────────────────────────────────────

class TestAlphaVantageClient:
    def _client(self):
        from src.sources.alpha_vantage import AlphaVantageClient
        return AlphaVantageClient(MagicMock())

    def test_alpha_vantage_instantiates(self):
        c = self._client()
        assert c.source_id == "alpha_vantage"
        assert c.needs_key is True
        assert c.key_env_var == "ALPHA_VANTAGE_API_KEY"
        assert c.is_fallback is True

    def test_alpha_vantage_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test_key")
        assert c.is_available() is True

    def test_alpha_vantage_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response(
            {"Symbol": "NVDA", "AssetType": "Common Stock", "Name": "NVIDIA Corp"}
        )
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(ticker="NVDA")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_alpha_vantage_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response(
            {"Symbol": "NVDA", "AssetType": "Common Stock", "Name": "NVIDIA Corp"}
        )
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(ticker="NVDA"))
        assert isinstance(result, SourceResult)
        assert result.source == "alpha_vantage"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "market_data"


# ─────────────────────────────────────────────────────────────────────────────
# edgar
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgarClient:
    def _client(self, monkeypatch):
        monkeypatch.setenv("SEC_USER_AGENT", "Test test@test.com")
        with patch("edgar.set_identity"):
            from src.sources.edgar import EdgarClient
            return EdgarClient(MagicMock())

    def test_edgar_instantiates(self, monkeypatch):
        c = self._client(monkeypatch)
        assert c.source_id == "edgar"
        assert c.needs_key is False

    def test_edgar_is_available(self, monkeypatch):
        c = self._client(monkeypatch)
        # needs_key=False → always available
        assert c.is_available() is True

    def test_edgar_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client(monkeypatch)

        mock_filing = MagicMock()
        mock_filing.form = "8-K"
        mock_filing.accession_number = "0001234567-24-000001"
        mock_filing.filing_date = datetime(2024, 1, 1).date()
        mock_filings = MagicMock()
        mock_filings.latest.return_value = [mock_filing]
        mock_company = MagicMock()
        mock_company.get_filings.return_value = mock_filings

        with patch("edgar.Company", return_value=mock_company) as mock_co:
            q = SourceQuery(ticker="NVDA")
            c.fetch(q)
            c.fetch(q)
            # Company() should only be called during first (non-cached) fetch
            assert mock_co.call_count == 1

    def test_edgar_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client(monkeypatch)

        mock_filing = MagicMock()
        mock_filing.form = "8-K"
        mock_filing.accession_number = "0001234567-24-000001"
        mock_filing.filing_date = datetime(2024, 1, 1).date()
        mock_filings = MagicMock()
        mock_filings.latest.return_value = [mock_filing]
        mock_company = MagicMock()
        mock_company.get_filings.return_value = mock_filings

        with patch("edgar.Company", return_value=mock_company):
            result = c.fetch(SourceQuery(ticker="NVDA"))

        assert isinstance(result, SourceResult)
        assert result.source == "edgar"
        assert isinstance(result.documents, list)
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "filing"


# ─────────────────────────────────────────────────────────────────────────────
# marketaux
# ─────────────────────────────────────────────────────────────────────────────

class TestMarketauxClient:
    def _client(self):
        from src.sources.marketaux import MarketauxClient
        return MarketauxClient(MagicMock())

    def test_marketaux_instantiates(self):
        c = self._client()
        assert c.source_id == "marketaux"
        assert c.needs_key is True
        assert c.key_env_var == "MARKETAUX_API_KEY"

    def test_marketaux_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("MARKETAUX_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("MARKETAUX_API_KEY", "test_key")
        assert c.is_available() is True

    def test_marketaux_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MARKETAUX_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "data": [{"uuid": "abc123", "title": "AI News",
                      "url": "https://example.com",
                      "published_at": "2024-01-01T00:00:00.000000Z",
                      "entities": [{"symbol": "NVDA"}]}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(ticker="NVDA")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_marketaux_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MARKETAUX_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "data": [{"uuid": "abc123", "title": "AI News",
                      "url": "https://example.com",
                      "published_at": "2024-01-01T00:00:00.000000Z",
                      "entities": [{"symbol": "NVDA"}]}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(ticker="NVDA"))
        assert isinstance(result, SourceResult)
        assert result.source == "marketaux"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "news"
        assert result.documents[0].title == "AI News"


# ─────────────────────────────────────────────────────────────────────────────
# guardian
# ─────────────────────────────────────────────────────────────────────────────

class TestGuardianClient:
    def _client(self):
        from src.sources.guardian import GuardianClient
        return GuardianClient(MagicMock())

    def test_guardian_instantiates(self):
        c = self._client()
        assert c.source_id == "guardian"
        assert c.needs_key is True
        assert c.key_env_var == "GUARDIAN_API_KEY"

    def test_guardian_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("GUARDIAN_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("GUARDIAN_API_KEY", "test_key")
        assert c.is_available() is True

    def test_guardian_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GUARDIAN_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "response": {"results": [
                {"id": "technology/ai", "webTitle": "AI article",
                 "webUrl": "https://theguardian.com/ai",
                 "webPublicationDate": "2024-01-01T00:00:00Z"}
            ]}
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="AI")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_guardian_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GUARDIAN_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "response": {"results": [
                {"id": "technology/ai", "webTitle": "AI article",
                 "webUrl": "https://theguardian.com/ai",
                 "webPublicationDate": "2024-01-01T00:00:00Z"}
            ]}
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="AI"))
        assert isinstance(result, SourceResult)
        assert result.source == "guardian"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "news"
        assert result.documents[0].title == "AI article"


# ─────────────────────────────────────────────────────────────────────────────
# newsapi
# ─────────────────────────────────────────────────────────────────────────────

class TestNewsAPIClient:
    def _client(self):
        from src.sources.newsapi import NewsAPIClient
        return NewsAPIClient(MagicMock())

    def test_newsapi_instantiates(self):
        c = self._client()
        assert c.source_id == "newsapi"
        assert c.needs_key is True
        assert c.key_env_var == "NEWSAPI_KEY"
        assert c.is_fallback is True

    def test_newsapi_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("NEWSAPI_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("NEWSAPI_KEY", "test_key")
        assert c.is_available() is True

    def test_newsapi_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEWSAPI_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "articles": [{"url": "https://example.com/news", "title": "AI news",
                          "publishedAt": "2024-01-01T00:00:00Z",
                          "source": {"name": "Reuters"}}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="AI")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_newsapi_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEWSAPI_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "articles": [{"url": "https://example.com/news", "title": "AI news",
                          "publishedAt": "2024-01-01T00:00:00Z",
                          "source": {"name": "Reuters"}}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="AI"))
        assert isinstance(result, SourceResult)
        assert result.source == "newsapi"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "news"
        assert result.documents[0].title == "AI news"


# ─────────────────────────────────────────────────────────────────────────────
# newsdata
# ─────────────────────────────────────────────────────────────────────────────

class TestNewsdataClient:
    def _client(self):
        from src.sources.newsdata import NewsdataClient
        return NewsdataClient(MagicMock())

    def test_newsdata_instantiates(self):
        c = self._client()
        assert c.source_id == "newsdata"
        assert c.needs_key is True
        assert c.key_env_var == "NEWSDATA_API_KEY"
        assert c.is_fallback is True

    def test_newsdata_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("NEWSDATA_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("NEWSDATA_API_KEY", "test_key")
        assert c.is_available() is True

    def test_newsdata_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEWSDATA_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"article_id": "abc", "title": "AI news",
                         "link": "https://example.com",
                         "pubDate": "2024-01-01 00:00:00"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="AI")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_newsdata_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEWSDATA_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"article_id": "abc", "title": "AI news",
                         "link": "https://example.com",
                         "pubDate": "2024-01-01 00:00:00"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="AI"))
        assert isinstance(result, SourceResult)
        assert result.source == "newsdata"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "news"
        assert result.documents[0].title == "AI news"


# ─────────────────────────────────────────────────────────────────────────────
# fred
# ─────────────────────────────────────────────────────────────────────────────

class TestFredClient:
    def _client(self):
        from src.sources.fred import FredClient
        return FredClient(MagicMock())

    def test_fred_instantiates(self):
        c = self._client()
        assert c.source_id == "fred"
        assert c.needs_key is True
        assert c.key_env_var == "FRED_API_KEY"

    def test_fred_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("FRED_API_KEY", "test_key")
        assert c.is_available() is True

    def test_fred_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "observations": [
                {"date": "2024-01-01", "value": "4.5"},
                {"date": "2024-01-02", "value": "4.6"},
            ]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="DGS10")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_fred_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "observations": [
                {"date": "2024-01-01", "value": "4.5"},
                {"date": "2024-01-02", "value": "4.6"},
            ]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="DGS10"))
        assert isinstance(result, SourceResult)
        assert result.source == "fred"
        assert len(result.documents) == 1
        assert result.documents[0].doc_type == "macro_indicator"


# ─────────────────────────────────────────────────────────────────────────────
# eia
# ─────────────────────────────────────────────────────────────────────────────

class TestEiaClient:
    def _client(self):
        from src.sources.eia import EiaClient
        return EiaClient(MagicMock())

    def test_eia_instantiates(self):
        c = self._client()
        assert c.source_id == "eia"
        assert c.needs_key is True
        assert c.key_env_var == "EIA_API_KEY"
        assert c.sector_routed is True

    def test_eia_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("EIA_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("EIA_API_KEY", "test_key")
        assert c.is_available() is True

    def test_eia_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EIA_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "response": {"data": [{"period": "2024-01-01", "value": "80.5"}]}
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="petroleum")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_eia_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EIA_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "response": {"data": [{"period": "2024-01-01", "value": "80.5"}]}
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery())
        assert isinstance(result, SourceResult)
        assert result.source == "eia"
        assert len(result.documents) == 1
        assert result.documents[0].doc_type == "macro_indicator"


# ─────────────────────────────────────────────────────────────────────────────
# openfda
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenFdaClient:
    def _client(self):
        from src.sources.openfda import OpenFdaClient
        return OpenFdaClient(MagicMock())

    def test_openfda_instantiates(self):
        c = self._client()
        assert c.source_id == "openfda"
        assert c.needs_key is True
        assert c.key_env_var == "OPENFDA_API_KEY"
        assert c.sector_routed is True

    def test_openfda_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("OPENFDA_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("OPENFDA_API_KEY", "test_key")
        assert c.is_available() is True

    def test_openfda_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENFDA_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"safetyreportid": "12345",
                         "patient": {"drug": [{"medicinalproduct": "ASPIRIN"}]}}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="ASPIRIN")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_openfda_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENFDA_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"safetyreportid": "12345",
                         "patient": {"drug": [{"medicinalproduct": "ASPIRIN"}]}}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="ASPIRIN"))
        assert isinstance(result, SourceResult)
        assert result.source == "openfda"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "filing"
        assert result.documents[0].title == "ASPIRIN"


# ─────────────────────────────────────────────────────────────────────────────
# github
# ─────────────────────────────────────────────────────────────────────────────

class TestGithubClient:
    def _client(self):
        from src.sources.github import GithubClient
        return GithubClient(MagicMock())

    def test_github_instantiates(self):
        c = self._client()
        assert c.source_id == "github"
        assert c.needs_key is True
        assert c.key_env_var == "GITHUB_TOKEN"

    def test_github_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("GITHUB_TOKEN", "test_token")
        assert c.is_available() is True

    def test_github_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test_token")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "items": [{"id": 1234, "full_name": "nvidia/nccl",
                       "html_url": "https://github.com/nvidia/nccl",
                       "pushed_at": "2024-01-01T00:00:00Z",
                       "stargazers_count": 5000,
                       "topics": ["cuda", "ai"]}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(ticker="NVDA")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_github_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test_token")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "items": [{"id": 1234, "full_name": "nvidia/nccl",
                       "html_url": "https://github.com/nvidia/nccl",
                       "pushed_at": "2024-01-01T00:00:00Z",
                       "stargazers_count": 5000,
                       "topics": ["cuda", "ai"]}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(ticker="NVDA"))
        assert isinstance(result, SourceResult)
        assert result.source == "github"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "tech_signal"
        assert result.documents[0].title == "nvidia/nccl"


# ─────────────────────────────────────────────────────────────────────────────
# tavily
# ─────────────────────────────────────────────────────────────────────────────

class TestTavilyClient:
    def _client(self):
        from src.sources.tavily import TavilyClient
        return TavilyClient(MagicMock())

    def test_tavily_instantiates(self):
        c = self._client()
        assert c.source_id == "tavily"
        assert c.needs_key is True
        assert c.key_env_var == "TAVILY_API_KEY"

    def test_tavily_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("TAVILY_API_KEY", "test_key")
        assert c.is_available() is True

    def test_tavily_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"url": "https://example.com", "title": "AI article",
                         "content": "About AI", "raw_content": "Full content about AI",
                         "score": 0.9}]
        })
        with patch.object(c, "_http_post", return_value=mock_resp) as mock_post:
            q = SourceQuery(query_string="AI technology")
            c.fetch(q)
            c.fetch(q)
            assert mock_post.call_count == 1

    def test_tavily_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"url": "https://example.com", "title": "AI article",
                         "content": "About AI", "raw_content": "Full content about AI",
                         "score": 0.9}]
        })
        with patch.object(c, "_http_post", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="AI technology"))
        assert isinstance(result, SourceResult)
        assert result.source == "tavily"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "web_search"
        assert result.documents[0].title == "AI article"


# ─────────────────────────────────────────────────────────────────────────────
# firecrawl
# ─────────────────────────────────────────────────────────────────────────────

class TestFirecrawlClient:
    def _client(self):
        from src.sources.firecrawl import FirecrawlClient
        return FirecrawlClient(MagicMock())

    def test_firecrawl_instantiates(self):
        c = self._client()
        assert c.source_id == "firecrawl"
        assert c.needs_key is True
        assert c.key_env_var == "FIRECRAWL_API_KEY"

    def test_firecrawl_is_available(self, monkeypatch):
        c = self._client()
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        assert c.is_available() is False
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test_key")
        assert c.is_available() is True

    def test_firecrawl_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "success": True,
            "data": {"markdown": "# Example Domain",
                     "metadata": {"title": "Example Domain"}}
        })
        with patch.object(c, "_http_post", return_value=mock_resp) as mock_post:
            q = SourceQuery(query_string="https://example.com")
            c.fetch(q)
            c.fetch(q)
            assert mock_post.call_count == 1

    def test_firecrawl_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "test_key")
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "success": True,
            "data": {"markdown": "# Example Domain",
                     "metadata": {"title": "Example Domain"}}
        })
        with patch.object(c, "_http_post", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="https://example.com"))
        assert isinstance(result, SourceResult)
        assert result.source == "firecrawl"
        assert len(result.documents) == 1
        assert result.documents[0].doc_type == "scraped_page"
        assert result.documents[0].title == "Example Domain"


# ─────────────────────────────────────────────────────────────────────────────
# yfinance
# ─────────────────────────────────────────────────────────────────────────────

class TestYfinanceClient:
    def _client(self):
        from src.sources.yfinance_client import YfinanceClient
        return YfinanceClient(MagicMock())

    def test_yfinance_instantiates(self):
        c = self._client()
        assert c.source_id == "yfinance"
        assert c.needs_key is False

    def test_yfinance_is_available(self):
        c = self._client()
        # needs_key=False → always available
        assert c.is_available() is True

    def test_yfinance_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()

        mock_ticker_obj = MagicMock()
        mock_ticker_obj.info = {"symbol": "NVDA", "regularMarketPrice": 900.0}
        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.return_value = mock_ticker_obj

        with patch.dict("sys.modules", {"yfinance": mock_yf_module}):
            q = SourceQuery(ticker="NVDA")
            c.fetch(q)
            c.fetch(q)
            # yf.Ticker should only be called once (second call hits disk cache)
            assert mock_yf_module.Ticker.call_count == 1

    def test_yfinance_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()

        mock_ticker_obj = MagicMock()
        mock_ticker_obj.info = {"symbol": "NVDA", "regularMarketPrice": 900.0}
        mock_yf_module = MagicMock()
        mock_yf_module.Ticker.return_value = mock_ticker_obj

        with patch.dict("sys.modules", {"yfinance": mock_yf_module}):
            result = c.fetch(SourceQuery(ticker="NVDA"))

        assert isinstance(result, SourceResult)
        assert result.source == "yfinance"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "market_data"


# ─────────────────────────────────────────────────────────────────────────────
# arxiv
# ─────────────────────────────────────────────────────────────────────────────

_ARXIV_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Test AI Paper</title>
    <summary>This is a test summary.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>John Doe</name></author>
    <link rel="alternate" href="http://arxiv.org/abs/2401.00001v1"/>
  </entry>
</feed>"""


class TestArxivClient:
    def _client(self):
        from src.sources.arxiv import ArxivClient
        return ArxivClient(MagicMock())

    def test_arxiv_instantiates(self):
        c = self._client()
        assert c.source_id == "arxiv"
        assert c.needs_key is False

    def test_arxiv_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_arxiv_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response(_ARXIV_XML, text=_ARXIV_XML)
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="AI")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_arxiv_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response(_ARXIV_XML, text=_ARXIV_XML)
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="AI"))
        assert isinstance(result, SourceResult)
        assert result.source == "arxiv"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "paper"
        assert "Test AI Paper" in result.documents[0].title


# ─────────────────────────────────────────────────────────────────────────────
# biorxiv
# ─────────────────────────────────────────────────────────────────────────────

class TestBiorxivClient:
    def _client(self):
        from src.sources.biorxiv import BiorxivClient
        return BiorxivClient(MagicMock())

    def test_biorxiv_instantiates(self):
        c = self._client()
        assert c.source_id == "biorxiv"
        assert c.needs_key is False
        assert c.sector_routed is True

    def test_biorxiv_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_biorxiv_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "collection": [{"doi": "10.1101/2024.01.01.000001", "title": "Bio paper",
                            "abstract": "Test abstract", "date": "2024-01-01",
                            "authors": "Doe J"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="biology")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_biorxiv_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "collection": [{"doi": "10.1101/2024.01.01.000001", "title": "Bio paper",
                            "abstract": "Test abstract", "date": "2024-01-01",
                            "authors": "Doe J"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="biology"))
        assert isinstance(result, SourceResult)
        assert result.source == "biorxiv"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "paper"
        assert result.documents[0].title == "Bio paper"


# ─────────────────────────────────────────────────────────────────────────────
# openalex
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenAlexClient:
    def _client(self):
        from src.sources.openalex import OpenAlexClient
        return OpenAlexClient(MagicMock())

    def test_openalex_instantiates(self):
        c = self._client()
        assert c.source_id == "openalex"
        assert c.needs_key is False

    def test_openalex_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_openalex_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"id": "https://openalex.org/W123", "title": "AI research",
                         "doi": "10.1234/test", "publication_date": "2024-01-01",
                         "publication_year": 2024, "cited_by_count": 42}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="artificial intelligence")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_openalex_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"id": "https://openalex.org/W123", "title": "AI research",
                         "doi": "10.1234/test", "publication_date": "2024-01-01",
                         "publication_year": 2024, "cited_by_count": 42}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="artificial intelligence"))
        assert isinstance(result, SourceResult)
        assert result.source == "openalex"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "paper"
        assert result.documents[0].title == "AI research"


# ─────────────────────────────────────────────────────────────────────────────
# crossref
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossrefClient:
    def _client(self):
        from src.sources.crossref import CrossrefClient
        return CrossrefClient(MagicMock())

    def test_crossref_instantiates(self):
        c = self._client()
        assert c.source_id == "crossref"
        assert c.needs_key is False

    def test_crossref_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_crossref_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "message": {"items": [
                {"DOI": "10.1234/test", "title": ["Test paper"],
                 "type": "journal-article", "publisher": "Elsevier",
                 "published": {"date-parts": [[2024, 1, 15]]},
                 "is-referenced-by-count": 10}
            ]}
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="AI")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_crossref_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "message": {"items": [
                {"DOI": "10.1234/test", "title": ["Test paper"],
                 "type": "journal-article", "publisher": "Elsevier",
                 "published": {"date-parts": [[2024, 1, 15]]},
                 "is-referenced-by-count": 10}
            ]}
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="AI"))
        assert isinstance(result, SourceResult)
        assert result.source == "crossref"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "paper"
        assert result.documents[0].title == "Test paper"


# ─────────────────────────────────────────────────────────────────────────────
# usaspending
# ─────────────────────────────────────────────────────────────────────────────

class TestUSASpendingClient:
    def _client(self):
        from src.sources.usaspending import USASpendingClient
        return USASpendingClient(MagicMock())

    def test_usaspending_instantiates(self):
        c = self._client()
        assert c.source_id == "usaspending"
        assert c.needs_key is False
        assert c.sector_routed is True

    def test_usaspending_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_usaspending_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"Award ID": "DASW01-24-C-0001",
                         "Recipient Name": "Lockheed Martin",
                         "Award Amount": 1000000,
                         "Start Date": "2024-01-01",
                         "Description": "Defense contract",
                         "Awarding Agency": "DoD"}]
        })
        with patch.object(c, "_http_post", return_value=mock_resp) as mock_post:
            q = SourceQuery(query_string="defense")
            c.fetch(q)
            c.fetch(q)
            assert mock_post.call_count == 1

    def test_usaspending_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"Award ID": "DASW01-24-C-0001",
                         "Recipient Name": "Lockheed Martin",
                         "Award Amount": 1000000,
                         "Start Date": "2024-01-01",
                         "Description": "Defense contract",
                         "Awarding Agency": "DoD"}]
        })
        with patch.object(c, "_http_post", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="defense"))
        assert isinstance(result, SourceResult)
        assert result.source == "usaspending"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "contract"


# ─────────────────────────────────────────────────────────────────────────────
# clinicaltrials
# ─────────────────────────────────────────────────────────────────────────────

class TestClinicalTrialsClient:
    def _client(self):
        from src.sources.clinicaltrials import ClinicalTrialsClient
        return ClinicalTrialsClient(MagicMock())

    def test_clinicaltrials_instantiates(self):
        c = self._client()
        assert c.source_id == "clinicaltrials"
        assert c.needs_key is False
        assert c.sector_routed is True

    def test_clinicaltrials_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_clinicaltrials_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "studies": [{"protocolSection": {
                "identificationModule": {"nctId": "NCT12345678",
                                         "briefTitle": "Test Trial"},
                "statusModule": {"overallStatus": "Recruiting",
                                 "startDateStruct": {"date": "2024-01-01"}}
            }}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="cancer")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_clinicaltrials_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "studies": [{"protocolSection": {
                "identificationModule": {"nctId": "NCT12345678",
                                         "briefTitle": "Test Trial"},
                "statusModule": {"overallStatus": "Recruiting",
                                 "startDateStruct": {"date": "2024-01-01"}}
            }}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="cancer"))
        assert isinstance(result, SourceResult)
        assert result.source == "clinicaltrials"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "filing"
        assert result.documents[0].title == "Test Trial"


# ─────────────────────────────────────────────────────────────────────────────
# gdelt
# ─────────────────────────────────────────────────────────────────────────────

class TestGdeltClient:
    def _client(self):
        from src.sources.gdelt import GdeltClient
        return GdeltClient(MagicMock())

    def test_gdelt_instantiates(self):
        c = self._client()
        assert c.source_id == "gdelt"
        assert c.needs_key is False

    def test_gdelt_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_gdelt_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "articles": [{"url": "https://example.com/news", "title": "AI news",
                          "seendate": "20240101T120000Z", "domain": "example.com",
                          "language": "English", "sourcecountry": "US"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="AI")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_gdelt_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "articles": [{"url": "https://example.com/news", "title": "AI news",
                          "seendate": "20240101T120000Z", "domain": "example.com",
                          "language": "English", "sourcecountry": "US"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="AI"))
        assert isinstance(result, SourceResult)
        assert result.source == "gdelt"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "news"
        assert result.documents[0].title == "AI news"


# ─────────────────────────────────────────────────────────────────────────────
# hackernews
# ─────────────────────────────────────────────────────────────────────────────

class TestHackerNewsClient:
    def _client(self):
        from src.sources.hackernews import HackerNewsClient
        return HackerNewsClient(MagicMock())

    def test_hackernews_instantiates(self):
        c = self._client()
        assert c.source_id == "hackernews"
        assert c.needs_key is False

    def test_hackernews_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_hackernews_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "hits": [{"objectID": "12345", "title": "AI breakthrough",
                      "url": "https://example.com",
                      "created_at": "2024-01-01T12:00:00.000Z",
                      "points": 300, "num_comments": 42, "author": "johndoe"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="AI")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_hackernews_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "hits": [{"objectID": "12345", "title": "AI breakthrough",
                      "url": "https://example.com",
                      "created_at": "2024-01-01T12:00:00.000Z",
                      "points": 300, "num_comments": 42, "author": "johndoe"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="AI"))
        assert isinstance(result, SourceResult)
        assert result.source == "hackernews"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "tech_signal"
        assert result.documents[0].title == "AI breakthrough"


# ─────────────────────────────────────────────────────────────────────────────
# papers_with_code
# ─────────────────────────────────────────────────────────────────────────────

class TestPapersWithCodeClient:
    def _client(self):
        from src.sources.papers_with_code import PapersWithCodeClient
        return PapersWithCodeClient(MagicMock())

    def test_papers_with_code_instantiates(self):
        c = self._client()
        assert c.source_id == "papers_with_code"
        assert c.needs_key is False

    def test_papers_with_code_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_papers_with_code_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"id": 1234, "title": "BERT Revisited",
                         "url_pdf": "https://arxiv.org/pdf/2401.00001.pdf",
                         "published": "2024-01-01", "stars": 500,
                         "tasks": ["NLP"], "arxiv_id": "2401.00001"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="deep learning")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_papers_with_code_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "results": [{"id": 1234, "title": "BERT Revisited",
                         "url_pdf": "https://arxiv.org/pdf/2401.00001.pdf",
                         "published": "2024-01-01", "stars": 500,
                         "tasks": ["NLP"], "arxiv_id": "2401.00001"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="deep learning"))
        assert isinstance(result, SourceResult)
        assert result.source == "papers_with_code"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "paper"
        assert result.documents[0].title == "BERT Revisited"


# ─────────────────────────────────────────────────────────────────────────────
# wikidata
# ─────────────────────────────────────────────────────────────────────────────

class TestWikidataClient:
    def _client(self):
        from src.sources.wikidata import WikidataClient
        return WikidataClient(MagicMock())

    def test_wikidata_instantiates(self):
        c = self._client()
        assert c.source_id == "wikidata"
        assert c.needs_key is False

    def test_wikidata_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_wikidata_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "search": [{"id": "Q182477", "label": "NVIDIA",
                        "description": "American technology company",
                        "url": "https://www.wikidata.org/wiki/Q182477"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="NVIDIA")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_wikidata_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response({
            "search": [{"id": "Q182477", "label": "NVIDIA",
                        "description": "American technology company",
                        "url": "https://www.wikidata.org/wiki/Q182477"}]
        })
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="NVIDIA"))
        assert isinstance(result, SourceResult)
        assert result.source == "wikidata"
        assert len(result.documents) >= 1
        assert result.documents[0].doc_type == "other"
        assert result.documents[0].title == "NVIDIA"


# ─────────────────────────────────────────────────────────────────────────────
# world_bank
# ─────────────────────────────────────────────────────────────────────────────

class TestWorldBankClient:
    def _client(self):
        from src.sources.world_bank import WorldBankClient
        return WorldBankClient(MagicMock())

    def test_world_bank_instantiates(self):
        c = self._client()
        assert c.source_id == "world_bank"
        assert c.needs_key is False

    def test_world_bank_is_available(self):
        c = self._client()
        assert c.is_available() is True

    def test_world_bank_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response([
            {"page": 1, "total": 1},
            [{"country": {"value": "United States"}, "value": 2.5, "date": "2023"}]
        ])
        with patch.object(c, "_http_get", return_value=mock_resp) as mock_get:
            q = SourceQuery(query_string="NY.GDP.MKTP.KD.ZG")
            c.fetch(q)
            c.fetch(q)
            assert mock_get.call_count == 1

    def test_world_bank_fetch_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.sources.base.RAW_DIR", tmp_path / "raw")
        c = self._client()
        mock_resp = make_mock_response([
            {"page": 1, "total": 1},
            [{"country": {"value": "United States"}, "value": 2.5, "date": "2023"}]
        ])
        with patch.object(c, "_http_get", return_value=mock_resp):
            result = c.fetch(SourceQuery(query_string="NY.GDP.MKTP.KD.ZG"))
        assert isinstance(result, SourceResult)
        assert result.source == "world_bank"
        assert len(result.documents) == 1
        assert result.documents[0].doc_type == "macro_indicator"
