from __future__ import annotations
import json
import logging
import re
from typing import Any

from src.sources.base import SourceDocument

logger = logging.getLogger("visionairy2.ingestion.extractor")

_SYSTEM = (
    "You extract company entities from text. "
    "Return ONLY a JSON array with no markdown fences, no explanation. "
    'Format: [{"name": "...", "ticker_guess": "TICK or null", "context": "brief reason"}]. '
    "Include at most 15 entities. If none found, return []."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


class EntityExtractor:
    def __init__(self, llm_client: Any) -> None:
        self._llm = llm_client

    def extract_companies(self, text: str, max_entities: int = 15) -> list[dict]:
        truncated = text[:4000]
        for attempt in range(2):
            try:
                raw = self._llm.complete(
                    role="entity_extraction",
                    system=_SYSTEM,
                    user=truncated,
                    max_tokens=1024,
                    agent_name="entity_extractor",
                )
                cleaned = _strip_fences(raw)
                entities = json.loads(cleaned)
                if isinstance(entities, list):
                    return entities[:max_entities]
            except (json.JSONDecodeError, Exception) as exc:
                if attempt == 0:
                    logger.debug("Entity extraction parse fail (attempt 1): %s", exc)
                    continue
                logger.warning("Entity extraction failed after 2 attempts: %s", exc)
        return []

    def extract_from_documents(self, documents: list[SourceDocument]) -> list[SourceDocument]:
        for doc in documents:
            text = doc.summary or doc.title or ""
            if not text:
                continue
            entities = self.extract_companies(text)
            doc.entities_mentioned = list({
                e.get("ticker_guess") or e.get("name", "")
                for e in entities
                if e.get("ticker_guess") or e.get("name")
            })
        return documents
