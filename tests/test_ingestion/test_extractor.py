from __future__ import annotations
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, call

from src.sources.base import SourceDocument
from src.ingestion.extractor import EntityExtractor


def _doc(title="NVIDIA announces new GPU", summary="Test"):
    return SourceDocument(
        source="test", source_id="d1", url="http://example.com",
        content_hash="abc123", doc_type="news", title=title,
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        fetched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        raw_payload={}, summary=summary,
    )


class TestEntityExtractor:
    def _make_extractor(self, llm_response: str):
        llm = MagicMock()
        llm.complete.return_value = llm_response
        return EntityExtractor(llm)

    def test_extracts_valid_json(self):
        response = '[{"name": "NVIDIA", "ticker_guess": "NVDA", "context": "GPU maker"}]'
        extractor = self._make_extractor(response)
        result = extractor.extract_companies("NVIDIA announces record GPU sales")
        assert len(result) == 1
        assert result[0]["ticker_guess"] == "NVDA"

    def test_strips_markdown_fences(self):
        response = '```json\n[{"name": "AMD", "ticker_guess": "AMD", "context": "chip maker"}]\n```'
        extractor = self._make_extractor(response)
        result = extractor.extract_companies("AMD releases new CPU")
        assert len(result) == 1
        assert result[0]["name"] == "AMD"

    def test_returns_empty_on_persistent_failure(self):
        llm = MagicMock()
        llm.complete.return_value = "this is not json at all"
        extractor = EntityExtractor(llm)
        result = extractor.extract_companies("Some text")
        assert result == []
        assert llm.complete.call_count == 2  # retried once

    def test_truncates_long_text(self):
        llm = MagicMock()
        llm.complete.return_value = "[]"
        extractor = EntityExtractor(llm)
        long_text = "x" * 10000
        extractor.extract_companies(long_text)
        # The text passed to complete should be <= 4000 chars
        call_kwargs = llm.complete.call_args[1]
        user_text = call_kwargs.get("user")
        assert user_text is not None
        assert len(user_text) <= 4000

    def test_extract_from_documents_mutates_entities(self):
        llm = MagicMock()
        llm.complete.return_value = '[{"name": "NVIDIA", "ticker_guess": "NVDA", "context": "GPU"}]'
        extractor = EntityExtractor(llm)
        docs = [_doc()]
        result = extractor.extract_from_documents(docs)
        assert "NVDA" in result[0].entities_mentioned

    def test_handles_empty_documents(self):
        llm = MagicMock()
        llm.complete.return_value = "[]"
        extractor = EntityExtractor(llm)
        result = extractor.extract_from_documents([])
        assert result == []

    def test_extract_multiple_entities(self):
        """Multiple entities in one response are all returned."""
        response = (
            '[{"name": "NVIDIA", "ticker_guess": "NVDA", "context": "GPU"}, '
            '{"name": "AMD", "ticker_guess": "AMD", "context": "CPU"}]'
        )
        extractor = self._make_extractor(response)
        result = extractor.extract_companies("Both NVIDIA and AMD reported results")
        assert len(result) == 2
        tickers = {e["ticker_guess"] for e in result}
        assert tickers == {"NVDA", "AMD"}

    def test_extract_from_documents_uses_summary_when_available(self):
        """extract_from_documents uses doc.summary as the text source."""
        llm = MagicMock()
        llm.complete.return_value = '[{"name": "Tesla", "ticker_guess": "TSLA", "context": "EV"}]'
        extractor = EntityExtractor(llm)
        doc = _doc(title="Irrelevant title", summary="Tesla beats earnings")
        extractor.extract_from_documents([doc])
        # The 'user' kwarg passed to complete should contain summary text
        call_kwargs = llm.complete.call_args[1]
        assert "Tesla beats earnings" in call_kwargs.get("user", "")

    def test_extract_from_documents_falls_back_to_title(self):
        """extract_from_documents uses title when summary is None."""
        llm = MagicMock()
        llm.complete.return_value = '[]'
        extractor = EntityExtractor(llm)
        doc = SourceDocument(
            source="test", source_id="d2", url="http://example.com",
            content_hash="xyz", doc_type="news", title="Boeing wins contract",
            published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            fetched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            raw_payload={}, summary=None,
        )
        extractor.extract_from_documents([doc])
        call_kwargs = llm.complete.call_args[1]
        assert "Boeing wins contract" in call_kwargs.get("user", "")

    def test_llm_called_with_correct_role(self):
        """complete() is called with role='entity_extraction'."""
        llm = MagicMock()
        llm.complete.return_value = "[]"
        extractor = EntityExtractor(llm)
        extractor.extract_companies("some text")
        call_kwargs = llm.complete.call_args[1]
        assert call_kwargs.get("role") == "entity_extraction"

    def test_max_entities_cap(self):
        """Returns at most max_entities results even when LLM returns more."""
        many = [{"name": f"Co{i}", "ticker_guess": f"C{i}", "context": "x"} for i in range(20)]
        import json
        extractor = self._make_extractor(json.dumps(many))
        result = extractor.extract_companies("text", max_entities=5)
        assert len(result) == 5
