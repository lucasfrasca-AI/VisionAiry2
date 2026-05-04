from __future__ import annotations
from src.sources.base import SourceDocument

# Source tier weights for collision resolution (higher = preferred)
_SOURCE_TIER: dict[str, int] = {
    "edgar": 10,
    "guardian": 8,
    "marketaux": 6,
    "finnhub": 7,
    "newsapi": 5,
    "newsdata": 5,
    "gdelt": 4,
    "hackernews": 4,
}
_DEFAULT_TIER = 4


def _tier(doc: SourceDocument) -> int:
    return _SOURCE_TIER.get(doc.source, _DEFAULT_TIER)


def _trigrams(s: str) -> set[str]:
    s = s.lower().strip()
    if len(s) < 3:
        return {s}
    return {s[i:i+3] for i in range(len(s) - 2)}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class Deduper:
    def hash_dedupe(self, documents: list[SourceDocument]) -> list[SourceDocument]:
        seen: set[str] = set()
        out: list[SourceDocument] = []
        for doc in documents:
            if doc.content_hash not in seen:
                seen.add(doc.content_hash)
                out.append(doc)
        return out

    def title_similarity_dedupe(
        self, documents: list[SourceDocument], threshold: float = 0.85
    ) -> list[SourceDocument]:
        kept: list[SourceDocument] = []
        for doc in documents:
            merged = False
            for i, existing in enumerate(kept):
                if _jaccard(doc.title or "", existing.title or "") >= threshold:
                    # Keep the one from the higher-tier source
                    if _tier(doc) > _tier(existing):
                        kept[i] = doc
                    merged = True
                    break
            if not merged:
                kept.append(doc)
        return kept

    def dedupe(self, documents: list[SourceDocument]) -> list[SourceDocument]:
        return self.title_similarity_dedupe(self.hash_dedupe(documents))
