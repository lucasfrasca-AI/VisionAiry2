from __future__ import annotations
import math
import re
from datetime import datetime, timezone
from typing import Any

from src.sources.base import SourceDocument

_EMERGING_SOURCES: frozenset[str] = frozenset({
    "polygon_ipo", "sbir", "edgar_fulltext", "nsf_awards",
    "sec_tickers_delta", "usaspending",
})

# These sources are queried with sector keywords, so their results are implicitly sector-relevant.
# Entities from these sources auto-pass the sector keyword check (threshold = 0).
_SECTOR_QUERIED_SOURCES: frozenset[str] = frozenset({
    "sbir", "edgar_fulltext", "nsf_awards",
})

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

EMERGING_CONFIDENCE_THRESHOLD: float = 8.0


def _slugify(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9-]+', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug[:60]


def _alphanumeric_count(name: str) -> int:
    return sum(1 for c in name if c.isalnum())


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
                # Sector-keyword-queried sources are implicitly sector-relevant; auto-pass.
                from_sector_queried = any(
                    getattr(d, "source", "") in _SECTOR_QUERIED_SOURCES for d in docs
                )
                if from_sector_queried:
                    kept.append({**candidate, "sector_status": "unresolved_kept"})
                    continue

                # For others: require ≥3 keyword matches normally; ≥1 if from any
                # emerging-signal source (those were already sector-context-fetched).
                if not active_keywords:
                    continue
                from_emerging_source = any(
                    getattr(d, "source", "") in _EMERGING_SOURCES for d in docs
                )
                matching = sum(
                    1 for d in docs
                    if any(
                        kw in (d.title or "").lower() or kw in (d.summary or "").lower()
                        for kw in active_keywords
                    )
                )
                threshold = 1 if from_emerging_source else 3
                if matching >= threshold:
                    kept.append({**candidate, "sector_status": "unresolved_kept"})
                # else: drop

        return kept

    def rank_companies(self, scores: list[dict]) -> list[dict]:
        return sorted(scores, key=lambda x: x["score"], reverse=True)

    def top_n(self, scores: list[dict], n: int = 7, min_score: float = 0.0) -> list[dict]:
        ranked = self.rank_companies(scores)
        return [s for s in ranked if s["score"] >= min_score][:n]

    # ──────────────────────────── two-track scoring ────────────────────────────

    def split_candidates(
        self,
        candidates: list[dict],
        config: Any,
    ) -> tuple[list[dict], list[dict]]:
        """Split into (established, emerging) buckets.

        ESTABLISHED: ticker in watchlist, OR fundamentals market_cap > $2B.
        EMERGING: not in watchlist AND at least one doc from an emerging-signal source.
        Everything else: discarded.
        """
        watchlist_tickers: set[str] = set()
        if config and hasattr(config, "watchlist"):
            for entries in config.watchlist.values():
                for e in entries:
                    t = e.ticker if hasattr(e, "ticker") else (e.get("ticker", "") if isinstance(e, dict) else "")
                    if t:
                        watchlist_tickers.add(t)

        established: list[dict] = []
        emerging: list[dict] = []

        for c in candidates:
            ticker = c.get("ticker", "")
            docs = c.get("docs", [])
            market_cap = c.get("market_cap")

            in_watchlist = ticker in watchlist_tickers
            large_cap = isinstance(market_cap, (int, float)) and market_cap > 2_000_000_000

            if in_watchlist or large_cap:
                established.append({**c, "track": "established"})
                continue

            has_emerging_signal = any(
                getattr(d, "source", "") in _EMERGING_SOURCES for d in docs
            )
            if has_emerging_signal:
                emerging.append({**c, "track": "emerging"})

        return established, emerging

    def score_emerging(
        self,
        company_id: str,
        document_links: list[tuple[SourceDocument, float]],
        config: Any,
        seen_tickers: set[str] | None = None,
    ) -> dict:
        """Emerging-company scoring: novelty + government validation + IPO signal."""
        now = datetime.now(timezone.utc)

        sources: set[str] = set()
        emerging_sources: set[str] = set()
        sector_match = False
        has_sbir_phase2 = False
        has_nsf_award = False
        has_ipo_pending = False
        ipo_sources: set[str] = set()
        has_s1 = False
        novelty_recent = False

        for doc, _weight in document_links:
            src = doc.source
            sources.add(src)
            if src in _EMERGING_SOURCES:
                emerging_sources.add(src)

            if src == "sbir" and "phase ii" in (doc.title or "").lower():
                has_sbir_phase2 = True
            if src == "nsf_awards":
                has_nsf_award = True
            if src in ("polygon_ipo", "finnhub") and doc.doc_type == "filing":
                title_low = (doc.title or "").lower()
                summary_low = (doc.summary or "").lower()
                if "pending" in title_low or "pending" in summary_low:
                    has_ipo_pending = True
                    ipo_sources.add(src)
            if src == "edgar_fulltext" and doc.doc_type == "filing":
                title_low = (doc.title or "").lower()
                if any(f in title_low for f in ("s-1", "f-1", "drs")):
                    has_s1 = True
            if doc.published_at:
                age = (now - doc.published_at).days
                if age <= 30:
                    novelty_recent = True

        if config and hasattr(config, "sectors"):
            sector_match = len(config.sectors) > 0

        is_first_appearance = seen_tickers is not None and _slugify(company_id) not in seen_tickers
        novelty_bonus = 5.0 if (is_first_appearance and novelty_recent) else 0.0
        emerging_signal_count = min(len(emerging_sources) * 2.0, 10.0)
        government_validation = (5.0 if has_sbir_phase2 else 0.0) + (3.0 if has_nsf_award else 0.0)
        ipo_imminence = 8.0 if has_ipo_pending else 0.0
        cross_source_ipo_boost = 3.0 if len(ipo_sources) >= 2 else 0.0
        filing_in_progress = 6.0 if has_s1 else 0.0
        source_diversity = float(len(sources)) * 0.5
        sector_bonus = 5.0 if sector_match else 0.0

        score = (
            novelty_bonus
            + emerging_signal_count
            + government_validation
            + ipo_imminence
            + cross_source_ipo_boost
            + filing_in_progress
            + source_diversity
            + sector_bonus
        )

        return {
            "company_id": company_id,
            "score": round(score, 3),
            "track": "emerging",
            "factors": {
                "novelty_bonus": novelty_bonus,
                "emerging_signal_count": emerging_signal_count,
                "government_validation": government_validation,
                "ipo_imminence": ipo_imminence,
                "cross_source_ipo_boost": cross_source_ipo_boost,
                "filing_in_progress": filing_in_progress,
                "source_diversity": source_diversity,
                "sector_match": sector_match,
            },
        }

    def filter_emerging_pre_ipo(
        self,
        scored_candidates: list[dict],
        watchlist_tickers: set[str],
        seen_slugs: set[str],
        emit_fn=None,
    ) -> tuple[list[dict], list[dict]]:
        """Three-layer gate for emerging/pre-IPO candidates. Returns (kept, dropped).

        Layer 1: Name filter — drop if < 8 alphanumeric chars ("S C S", "P", "E").
        Layer 2: Subsidiary filter — drop if name contains any watchlist ticker (>= 3 chars)
                 as a word boundary ("BAE Systems Space & Mission Systems Inc").
        Layer 3: Confidence threshold — drop if score < EMERGING_CONFIDENCE_THRESHOLD.
        """
        kept: list[dict] = []
        dropped: list[dict] = []

        for c in scored_candidates:
            name = c.get("company_id", "")
            score = c.get("score", 0.0)

            # Layer 1: name too short
            alnum_len = _alphanumeric_count(name)
            if alnum_len < 8:
                reason = f"name too short ({alnum_len} alphanumeric chars)"
                if emit_fn:
                    emit_fn(f"[discover] Pre-IPO candidate {name!r} dropped: {reason} (score={score:.1f})")
                dropped.append({**c, "_drop_reason": reason})
                continue

            # Layer 2: subsidiary/brand of a known watchlist company
            matched_ticker = None
            for ticker in watchlist_tickers:
                if len(ticker) < 3:
                    continue
                if re.search(r'\b' + re.escape(ticker) + r'\b', name, re.IGNORECASE):
                    matched_ticker = ticker
                    break
            if matched_ticker:
                reason = f"subsidiary/brand of {matched_ticker}"
                if emit_fn:
                    emit_fn(f"[discover] Pre-IPO candidate {name!r} dropped: {reason} (score={score:.1f})")
                dropped.append({**c, "_drop_reason": reason})
                continue

            # Layer 3: confidence threshold
            if score < EMERGING_CONFIDENCE_THRESHOLD:
                reason = f"below threshold ({score:.1f} < {EMERGING_CONFIDENCE_THRESHOLD})"
                if emit_fn:
                    emit_fn(f"[discover] Pre-IPO candidate {name!r} dropped: {reason} (score={score:.1f})")
                dropped.append({**c, "_drop_reason": reason})
                continue

            kept.append(c)

        return kept, dropped

    def rank_two_tracks(
        self,
        established_scores: list[dict],
        emerging_scores: list[dict],
        n_established: int = 3,
        n_emerging: int = 2,
    ) -> dict:
        """Returns top candidates from each track plus split stats."""
        top_est = self.top_n(established_scores, n=n_established)
        top_em = self.top_n(emerging_scores, n=n_emerging)
        return {
            "established": top_est,
            "emerging": top_em,
            "split_stats": {
                "total_candidates": len(established_scores) + len(emerging_scores),
                "established_pool": len(established_scores),
                "emerging_pool": len(emerging_scores),
                "n_established_selected": len(top_est),
                "n_emerging_selected": len(top_em),
            },
        }
