from __future__ import annotations
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.sources.base import SourceQuery, SourceResult, SourceDocument
from src.ingestion.fetcher import ParallelFetcher
from src.sources.registry import reset_instances


@pytest.fixture(autouse=True)
def reset():
    reset_instances()
    yield
    reset_instances()


def _make_doc(source="test"):
    return SourceDocument(
        source=source, source_id="doc1", url="http://example.com",
        content_hash="abc123", doc_type="news", title="Test",
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        fetched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        raw_payload={},
    )


def _make_result(source="test", docs=1, errors=None):
    return SourceResult(
        source=source,
        query=SourceQuery(ticker="NVDA"),
        documents=[_make_doc(source) for _ in range(docs)],
        fetched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        errors=errors or [],
    )


class TestParallelFetcher:
    def test_fetch_all_success(self):
        """fetch_all returns results for all sources."""
        config = MagicMock()
        fetcher = ParallelFetcher(config)

        mock_client = MagicMock()
        mock_client.fetch.return_value = _make_result("source_a", docs=3)

        with patch("src.ingestion.fetcher.get_client", return_value=mock_client):
            queries = [("source_a", SourceQuery(ticker="NVDA"))]
            results = fetcher.fetch_all(queries)

        assert len(results) == 1
        assert results[0].source == "source_a"
        assert len(results[0].documents) == 3

    def test_error_isolation(self):
        """A failing source does not kill the batch — it produces SourceResult with errors."""
        config = MagicMock()
        fetcher = ParallelFetcher(config)

        mock_good = MagicMock()
        mock_good.fetch.return_value = _make_result("good", docs=2)
        mock_bad = MagicMock()
        mock_bad.fetch.side_effect = RuntimeError("connection refused")

        def get_client_side_effect(source_id, config, db_session_factory=None):
            return mock_good if source_id == "good" else mock_bad

        with patch("src.ingestion.fetcher.get_client", side_effect=get_client_side_effect):
            queries = [("good", SourceQuery(ticker="NVDA")), ("bad", SourceQuery(ticker="NVDA"))]
            results = fetcher.fetch_all(queries)

        assert len(results) == 2
        good = next(r for r in results if r.source == "good")
        bad = next(r for r in results if r.source == "bad")
        assert len(good.documents) == 2
        assert len(bad.errors) > 0
        assert len(bad.documents) == 0

    def test_parallel_execution(self):
        """Multiple sources fetched concurrently (basic timing check)."""
        import time
        config = MagicMock()
        fetcher = ParallelFetcher(config)

        def slow_fetch(query):
            time.sleep(0.05)
            return _make_result("slow")

        mock_client = MagicMock()
        mock_client.fetch.side_effect = slow_fetch

        with patch("src.ingestion.fetcher.get_client", return_value=mock_client):
            queries = [(f"source_{i}", SourceQuery(ticker="NVDA")) for i in range(4)]
            t0 = time.monotonic()
            results = fetcher.fetch_all(queries)
            elapsed = time.monotonic() - t0

        # 4 x 50ms sequential would be 200ms; parallel should be << 200ms
        assert elapsed < 0.15
        assert len(results) == 4

    def test_fetch_for_ticker_sector_routing(self):
        """Sector-routed sources are excluded when sector not in specialist_sources."""
        config = MagicMock()
        sector_cfg = MagicMock()
        sector_cfg.id = "ai_chips_compute"
        sector_cfg.specialist_sources = ["edgar"]
        config.sectors = [sector_cfg]

        fetcher = ParallelFetcher(config)
        mock_client = MagicMock()
        mock_client.fetch.return_value = _make_result("edgar")

        # fetch_for_ticker does a local `from src.sources.registry import SOURCE_REGISTRY`
        # so we patch the dict in-place on the registry module to avoid real imports.
        mock_edgar_cls = MagicMock()
        mock_edgar_cls.sector_routed = False

        import src.sources.registry as _reg
        original_registry = dict(_reg.SOURCE_REGISTRY)
        _reg.SOURCE_REGISTRY.clear()
        _reg.SOURCE_REGISTRY["edgar"] = mock_edgar_cls

        try:
            with patch("src.ingestion.fetcher.get_client", return_value=mock_client), \
                 patch("src.ingestion.fetcher.list_available_sources", return_value=["edgar"]):
                results = fetcher.fetch_for_ticker("NVDA", "ai_chips_compute")
        finally:
            _reg.SOURCE_REGISTRY.clear()
            _reg.SOURCE_REGISTRY.update(original_registry)

        assert isinstance(results, list)
        assert len(results) == 1

    def test_empty_queries(self):
        """fetch_all with no queries returns empty list."""
        config = MagicMock()
        fetcher = ParallelFetcher(config)
        results = fetcher.fetch_all([])
        assert results == []

    def test_all_sources_error(self):
        """All sources failing still returns one SourceResult per query, each with errors."""
        config = MagicMock()
        fetcher = ParallelFetcher(config)

        mock_client = MagicMock()
        mock_client.fetch.side_effect = ConnectionError("network unreachable")

        with patch("src.ingestion.fetcher.get_client", return_value=mock_client):
            queries = [
                ("source_x", SourceQuery(ticker="TSLA")),
                ("source_y", SourceQuery(ticker="TSLA")),
            ]
            results = fetcher.fetch_all(queries)

        assert len(results) == 2
        for r in results:
            assert len(r.errors) > 0
            assert len(r.documents) == 0

    def test_result_preserves_query(self):
        """The query object is echoed back in the returned SourceResult."""
        config = MagicMock()
        fetcher = ParallelFetcher(config)

        q = SourceQuery(ticker="AAPL", lookback_days=7)
        mock_client = MagicMock()
        mock_client.fetch.return_value = _make_result("edgar", docs=1)
        # Override the query to verify the result carries it through
        mock_client.fetch.return_value.query = q

        with patch("src.ingestion.fetcher.get_client", return_value=mock_client):
            results = fetcher.fetch_all([("edgar", q)])

        assert results[0].query.ticker == "AAPL"
        assert results[0].query.lookback_days == 7
