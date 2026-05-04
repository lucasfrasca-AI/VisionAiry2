from __future__ import annotations
import pytest
from datetime import datetime, timezone

from src.sources.base import SourceDocument
from src.ingestion.deduper import Deduper


def _doc(source="test", source_id="d1", content_hash="abc", title="Test Article", doc_type="news"):
    return SourceDocument(
        source=source, source_id=source_id, url="http://example.com",
        content_hash=content_hash, doc_type=doc_type, title=title,
        published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        fetched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        raw_payload={},
    )


class TestDeduper:
    def test_hash_dedupe_removes_duplicates(self):
        d = Deduper()
        docs = [
            _doc(source_id="a", content_hash="hash1"),
            _doc(source_id="b", content_hash="hash1"),  # duplicate hash
            _doc(source_id="c", content_hash="hash2"),
        ]
        result = d.hash_dedupe(docs)
        assert len(result) == 2
        hashes = {doc.content_hash for doc in result}
        assert hashes == {"hash1", "hash2"}

    def test_hash_dedupe_preserves_unique(self):
        d = Deduper()
        docs = [_doc(content_hash=f"hash{i}") for i in range(5)]
        result = d.hash_dedupe(docs)
        assert len(result) == 5

    def test_hash_dedupe_keeps_first_seen(self):
        """hash_dedupe keeps the first occurrence when hashes collide."""
        d = Deduper()
        docs = [
            _doc(source_id="first", content_hash="dup"),
            _doc(source_id="second", content_hash="dup"),
        ]
        result = d.hash_dedupe(docs)
        assert len(result) == 1
        assert result[0].source_id == "first"

    def test_title_similarity_keeps_higher_tier(self):
        """On near-duplicate titles, keeps the doc from the higher-tier source."""
        d = Deduper()
        # edgar tier=10, newsapi tier=5
        high_tier = _doc(source="edgar", source_id="a", content_hash="h1",
                         title="NVIDIA Reports Record Earnings")
        low_tier = _doc(source="newsapi", source_id="b", content_hash="h2",
                        title="NVIDIA Reports Record Earning")
        result = d.title_similarity_dedupe([low_tier, high_tier])
        assert len(result) == 1
        assert result[0].source == "edgar"

    def test_title_similarity_keeps_distinct(self):
        """Non-similar titles are both kept."""
        d = Deduper()
        docs = [
            _doc(content_hash="h1", title="NVIDIA Reports Record Earnings"),
            _doc(content_hash="h2", title="Lockheed Martin Wins Defense Contract"),
            _doc(content_hash="h3", title="Apple Releases New iPhone"),
        ]
        result = d.title_similarity_dedupe(docs)
        assert len(result) == 3

    def test_title_similarity_identical_titles(self):
        """Identical titles deduplicate to one doc, keeping the higher-tier source."""
        d = Deduper()
        docs = [
            _doc(source="newsdata", content_hash="h1", title="SpaceX launches rocket"),
            _doc(source="guardian", content_hash="h2", title="SpaceX launches rocket"),
        ]
        result = d.title_similarity_dedupe(docs)
        assert len(result) == 1
        # guardian (tier 8) > newsdata (tier 5)
        assert result[0].source == "guardian"

    def test_dedupe_combines_both(self):
        """dedupe() applies hash dedup then title similarity dedup."""
        d = Deduper()
        docs = [
            _doc(source="edgar", content_hash="h1", title="NVIDIA Reports Record Earnings"),
            _doc(source="newsapi", content_hash="h1", title="NVIDIA Reports Record Earnings"),  # same hash
            _doc(source="guardian", content_hash="h2", title="NVIDIA Reports Record Earning"),  # near-dup title (jaccard > 0.85)
            _doc(source="arxiv", content_hash="h3", title="Quantum Computing Progress"),  # distinct
        ]
        result = d.dedupe(docs)
        # h1 duplicates merged to 1 (edgar wins first-seen in hash_dedupe)
        # After hash_dedupe: h1 (edgar), h2 (guardian), h3 (arxiv)
        # After title_dedupe: h1 and h2 are near-dups; edgar(10) > guardian(8), keep edgar; h3 kept
        assert len(result) == 2
        sources = {doc.source for doc in result}
        assert "edgar" in sources
        assert "arxiv" in sources

    def test_empty_input(self):
        d = Deduper()
        assert d.dedupe([]) == []

    def test_hash_dedupe_empty(self):
        d = Deduper()
        assert d.hash_dedupe([]) == []

    def test_title_similarity_dedupe_empty(self):
        d = Deduper()
        assert d.title_similarity_dedupe([]) == []

    def test_single_document_passes_through(self):
        """A single document is never filtered out."""
        d = Deduper()
        doc = _doc(content_hash="only", title="Unique headline about nothing else")
        assert d.dedupe([doc]) == [doc]
