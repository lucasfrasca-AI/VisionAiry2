from __future__ import annotations
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from src.sources.base import SourceDocument
from src.ingestion.scorer import InterestingnessScorer


def _doc(source="edgar", doc_type="news", days_ago=1):
    return SourceDocument(
        source=source, source_id="d1", url="http://example.com",
        content_hash="abc123", doc_type=doc_type, title="Test",
        published_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        fetched_at=datetime.now(timezone.utc),
        raw_payload={},
    )


class TestInterestingnessScorer:
    def test_score_company_returns_dict(self):
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = [MagicMock()]
        doc_links = [(_doc("edgar", "news", 1), 1.0)]
        result = scorer.score_company("company_1", doc_links, config)
        assert "company_id" in result
        assert "score" in result
        assert "factors" in result
        assert result["company_id"] == "company_1"

    def test_score_factors_present(self):
        """All expected factor keys are present in the returned factors dict."""
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = [MagicMock()]
        result = scorer.score_company("c1", [(_doc(), 1.0)], config)
        expected_keys = {
            "recency", "source_diversity", "source_tier_avg",
            "sector_match", "insider_signal", "contract_signal", "paper_signal",
        }
        assert expected_keys.issubset(result["factors"].keys())

    def test_insider_signal_adds_score(self):
        """An insider-type document raises the score compared to a plain news doc."""
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = [MagicMock()]
        # Use the same source so the only variable is doc_type
        no_insider = scorer.score_company("c1", [(_doc("edgar", "news"), 1.0)], config)
        with_insider = scorer.score_company("c2", [(_doc("edgar", "insider"), 1.0)], config)
        assert with_insider["score"] > no_insider["score"]

    def test_contract_signal_adds_score(self):
        """A contract-type document raises the score relative to a baseline edgar news doc."""
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = [MagicMock()]
        no_contract = scorer.score_company("c1", [(_doc("edgar", "news"), 1.0)], config)
        with_contract = scorer.score_company("c2", [(_doc("usaspending", "contract"), 1.0)], config)
        assert with_contract["score"] > no_contract["score"]

    def test_paper_signal_adds_score(self):
        """A paper-type document raises the score compared to a news doc from the same source."""
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = [MagicMock()]
        # Use edgar for both so tier is identical; only doc_type differs
        no_paper = scorer.score_company("c1", [(_doc("edgar", "news"), 1.0)], config)
        with_paper = scorer.score_company("c2", [(_doc("edgar", "paper"), 1.0)], config)
        assert with_paper["score"] > no_paper["score"]

    def test_recency_favors_recent(self):
        """A document from yesterday scores higher than the same document from 60 days ago."""
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = [MagicMock()]
        recent = scorer.score_company("c1", [(_doc("edgar", "news", 1), 1.0)], config)
        old = scorer.score_company("c2", [(_doc("edgar", "news", 60), 1.0)], config)
        assert recent["score"] > old["score"]

    def test_source_diversity_adds_score(self):
        """More distinct sources raises the score compared to a single source."""
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = [MagicMock()]
        single = scorer.score_company("c1", [(_doc("edgar"), 1.0)], config)
        multi = scorer.score_company("c2", [
            (_doc("edgar"), 1.0), (_doc("guardian"), 1.0), (_doc("arxiv"), 1.0)
        ], config)
        assert multi["score"] > single["score"]

    def test_sector_match_true_when_sectors_present(self):
        """sector_match is True when config.sectors is non-empty."""
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = [MagicMock()]
        result = scorer.score_company("c1", [(_doc(), 1.0)], config)
        assert result["factors"]["sector_match"] is True

    def test_sector_match_false_when_no_sectors(self):
        """sector_match is False when config.sectors is empty."""
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = []
        result = scorer.score_company("c1", [(_doc(), 1.0)], config)
        assert result["factors"]["sector_match"] is False

    def test_rank_companies_descending(self):
        scorer = InterestingnessScorer()
        scores = [
            {"company_id": "c1", "score": 5.0, "factors": {}},
            {"company_id": "c2", "score": 15.0, "factors": {}},
            {"company_id": "c3", "score": 8.0, "factors": {}},
        ]
        ranked = scorer.rank_companies(scores)
        assert ranked[0]["score"] == 15.0
        assert ranked[-1]["score"] == 5.0

    def test_top_n_limits(self):
        scorer = InterestingnessScorer()
        scores = [
            {"company_id": f"c{i}", "score": float(i), "factors": {}}
            for i in range(20)
        ]
        top = scorer.top_n(scores, n=7)
        assert len(top) == 7
        assert top[0]["score"] == 19.0

    def test_empty_input(self):
        """Empty inputs do not raise and return sensible defaults."""
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = []
        result = scorer.score_company("c1", [], config)
        # score is a float (possibly negative due to sector penalty) — just check it doesn't crash
        assert isinstance(result["score"], float)
        assert scorer.rank_companies([]) == []
        assert scorer.top_n([]) == []

    def test_top_n_default_returns_all_when_fewer_than_n(self):
        """top_n with n=7 and only 3 items returns all 3."""
        scorer = InterestingnessScorer()
        scores = [{"company_id": f"c{i}", "score": float(i), "factors": {}} for i in range(3)]
        result = scorer.top_n(scores, n=7)
        assert len(result) == 3

    def test_score_is_rounded(self):
        """Returned score is rounded to 3 decimal places."""
        scorer = InterestingnessScorer()
        config = MagicMock()
        config.sectors = [MagicMock()]
        result = scorer.score_company("c1", [(_doc(), 1.0)], config)
        # Check that score matches its own rounded value to 3dp
        assert result["score"] == round(result["score"], 3)
