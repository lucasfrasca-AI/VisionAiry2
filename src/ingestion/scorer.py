from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Any

from src.sources.base import SourceDocument

_SOURCE_TIER: dict[str, float] = {
    "edgar": 10.0,
    "guardian": 8.0,
    "finnhub": 7.0,
    "marketaux": 6.0,
    "newsapi": 5.0,
    "newsdata": 5.0,
    "fred": 6.0,
    "eia": 5.0,
    "openfda": 7.0,
    "arxiv": 7.0,
    "openalex": 7.0,
    "crossref": 6.0,
    "usaspending": 8.0,
    "clinicaltrials": 7.0,
    "gdelt": 4.0,
    "hackernews": 4.0,
    "papers_with_code": 6.0,
    "biorxiv": 6.0,
    "github": 5.0,
    "tavily": 4.0,
    "firecrawl": 3.0,
    "yfinance": 4.0,
    "wikidata": 3.0,
    "world_bank": 5.0,
    "alpha_vantage": 5.0,
    "findata": 7.0,
    "fmp": 6.0,
}
_DEFAULT_TIER = 4.0


class InterestingnessScorer:
    def score_company(
        self,
        company_id: str,
        document_links: list[tuple[SourceDocument, float]],
        config: Any,
    ) -> dict:
        now = datetime.now(timezone.utc)

        recency_scores: list[float] = []
        sources: set[str] = set()
        tier_weights: list[float] = []
        has_insider = False
        contract_count = 0
        paper_count = 0
        sector_match = False

        for doc, weight in document_links:
            # Recency: exponential decay with 7-day half-life
            if doc.published_at:
                age_days = max(0.0, (now - doc.published_at).total_seconds() / 86400)
                recency_scores.append(math.exp(-0.099 * age_days))  # ln(2)/7 ≈ 0.099
            sources.add(doc.source)
            tier_weights.append(_SOURCE_TIER.get(doc.source, _DEFAULT_TIER))

            if doc.doc_type == "insider":
                has_insider = True
            if doc.doc_type == "contract":
                contract_count += 1
            if doc.doc_type == "paper":
                paper_count += 1

        recency = sum(recency_scores) / len(recency_scores) if recency_scores else 0.0
        source_diversity = float(len(sources))
        source_tier_avg = sum(tier_weights) / len(tier_weights) if tier_weights else _DEFAULT_TIER

        # Sector match: check if company sector matches an active sector in config
        if config and hasattr(config, "sectors"):
            sector_match = len(config.sectors) > 0

        insider_signal = 3.0 if has_insider else 0.0
        contract_signal = min(5.0 * contract_count, 20.0)
        paper_signal = min(2.0 * paper_count, 10.0)
        sector_bonus = 5.0 if sector_match else -2.0

        score = (
            recency * 1.2
            + source_diversity * 1.0
            + source_tier_avg * 1.0
            + sector_bonus * 1.5
            + insider_signal * 1.0
            + contract_signal * 1.0
            + paper_signal * 1.0
        )

        return {
            "company_id": company_id,
            "score": round(score, 3),
            "factors": {
                "recency": round(recency, 3),
                "source_diversity": source_diversity,
                "source_tier_avg": round(source_tier_avg, 3),
                "sector_match": sector_match,
                "insider_signal": insider_signal,
                "contract_signal": contract_signal,
                "paper_signal": paper_signal,
            },
        }

    def filter_to_sector(
        self,
        candidates: list[dict],
        active_sectors: list[str],
        adjacency_map: dict[str, list[str]],
        config: Any,
    ) -> list[dict]:
        """Stage-A hard sector gate. Returns only candidates in active or adjacent sectors.

        Each candidate dict must have 'ticker'; optionally 'docs' (list of SourceDocument).
        Adds 'sector_status': 'active' | 'adjacent' | 'unresolved_kept' to kept candidates.
        Drops candidates whose resolved sector is off-sector and unresolved candidates with
        fewer than 3 keyword-matching documents.
        """
        # Build ticker -> watchlist sector from config
        watchlist_sector: dict[str, str] = {}
        if config and hasattr(config, "watchlist"):
            for sid, entries in (config.watchlist or {}).items():
                for entry in entries:
                    if hasattr(entry, "ticker"):
                        t = entry.ticker
                    elif isinstance(entry, dict):
                        t = entry.get("ticker", "")
                    else:
                        t = ""
                    if t:
                        watchlist_sector[t] = sid

        # All sectors reachable from any active sector via one hop
        all_adjacent: set[str] = set()
        for active in active_sectors:
            for adj in adjacency_map.get(active, []):
                all_adjacent.add(adj)

        # Keywords for active sectors (used to qualify unresolved tickers)
        active_keywords: list[str] = []
        if config and hasattr(config, "sectors"):
            for s in config.sectors:
                if s.id in active_sectors:
                    active_keywords.extend(kw.lower() for kw in s.keywords)

        kept: list[dict] = []
        for candidate in candidates:
            ticker = candidate.get("ticker", "")
            docs = candidate.get("docs", [])
            sector_id = watchlist_sector.get(ticker)

            if sector_id is not None:
                if sector_id in active_sectors:
                    kept.append({**candidate, "sector_status": "active"})
                elif sector_id in all_adjacent:
                    kept.append({**candidate, "sector_status": "adjacent"})
                # else: resolved but off-sector → drop
            else:
                # Unresolved: keep only if ≥3 docs match active sector keywords
                if not active_keywords:
                    continue
                matching = sum(
                    1 for d in docs
                    if any(
                        kw in (d.title or "").lower() or kw in (d.summary or "").lower()
                        for kw in active_keywords
                    )
                )
                if matching >= 3:
                    kept.append({**candidate, "sector_status": "unresolved_kept"})
                # else: drop

        return kept

    def rank_companies(self, scores: list[dict]) -> list[dict]:
        return sorted(scores, key=lambda x: x["score"], reverse=True)

    def top_n(self, scores: list[dict], n: int = 7, min_score: float = 0.0) -> list[dict]:
        ranked = self.rank_companies(scores)
        return [s for s in ranked if s["score"] >= min_score][:n]
