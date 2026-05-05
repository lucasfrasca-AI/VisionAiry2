"""Base class and shared dataclasses for all source clients."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = ROOT / "data" / "raw"


# ─────────────────────────────────────────────────────────────────────────────
# Shared data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SourceQuery:
    ticker: Optional[str] = None
    query_string: Optional[str] = None
    lookback_days: Optional[int] = None
    limit: int = 25
    sector_id: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceDocument:
    source: str
    source_id: str
    url: str
    content_hash: str
    doc_type: str  # filing|news|paper|patent|contract|insider|earnings|sentiment|macro_indicator|tech_signal|web_search|scraped_page|market_data|other
    title: str
    published_at: Optional[datetime]
    fetched_at: datetime
    raw_payload: dict[str, Any]
    summary: Optional[str] = None
    entities_mentioned: list[str] = field(default_factory=list)


@dataclass
class SourceResult:
    source: str
    query: SourceQuery
    documents: list[SourceDocument]
    fetched_at: datetime
    errors: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Custom exceptions
# ─────────────────────────────────────────────────────────────────────────────

class SourceClientError(Exception):
    pass


class SourceAuthError(SourceClientError):
    pass


class SourceRateLimitError(SourceClientError):
    pass


class SourceUnavailableError(SourceClientError):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Base client
# ─────────────────────────────────────────────────────────────────────────────

class BaseSourceClient(ABC):
    source_id: str = ""
    needs_key: bool = True
    key_env_var: Optional[str] = None
    rate_limit_per_sec: float = 1.0
    cache_ttl_seconds: int = 3600
    is_fallback: bool = False
    sector_routed: bool = False

    def __init__(self, config: Any, db_session_factory: Any = None) -> None:
        self._config = config
        self._db_session_factory = db_session_factory
        self._last_request_time: float = 0.0
        self._logger = logging.getLogger(f"visionairy2.sources.{self.source_id}")

    def is_available(self) -> bool:
        if not self.needs_key:
            return True
        if not self.key_env_var:
            return False
        val = os.environ.get(self.key_env_var, "").strip()
        if not val:
            # Fall back to config.secrets when .env is not in os.environ
            try:
                secrets = getattr(self._config, "secrets", None)
                if secrets is None:
                    return False
                cfg_val = getattr(secrets, self.key_env_var, None)
                if not (isinstance(cfg_val, str) and cfg_val.strip()):
                    return False
                val = cfg_val.strip()
            except Exception:
                return False

        # Key is set — also check .key_status.json; if validated INVALID, treat as unavailable
        status_path = Path(__file__).resolve().parent.parent.parent / "data" / ".key_status.json"
        if status_path.exists():
            try:
                import json as _json
                statuses = _json.loads(status_path.read_text()).get("statuses", {})
                key_status = statuses.get(self.key_env_var, {}).get("status")
                if key_status == "INVALID":
                    return False
            except Exception:
                pass  # fail open — don't block a source if status file is unreadable

        return True

    @abstractmethod
    def fetch(self, query: SourceQuery) -> SourceResult:
        ...

    def _rate_limit(self) -> None:
        if self.rate_limit_per_sec <= 0:
            return
        min_interval = 1.0 / self.rate_limit_per_sec
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.monotonic()

    def _http_get(
        self,
        url: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> httpx.Response:
        return self._http_request("GET", url, params=params, headers=headers)

    def _http_post(
        self,
        url: str,
        json: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> httpx.Response:
        return self._http_request("POST", url, json_body=json, headers=headers)

    def _http_request(
        self,
        method: str,
        url: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> httpx.Response:
        max_attempts = 3
        base_delay = 1.0
        cap_delay = 8.0

        for attempt in range(max_attempts):
            self._rate_limit()
            try:
                resp = httpx.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=30.0,
                    follow_redirects=True,
                )
            except Exception as exc:
                if attempt == max_attempts - 1:
                    raise SourceClientError(f"{self.source_id} request failed: {exc}") from exc
                time.sleep(min(base_delay * (2 ** attempt), cap_delay))
                continue

            if resp.status_code in (401, 403):
                raise SourceAuthError(
                    f"{self.source_id} auth error {resp.status_code}: {resp.text[:200]}"
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == max_attempts - 1:
                    raise SourceRateLimitError(
                        f"{self.source_id} rate/server error {resp.status_code}"
                    )
                delay = min(base_delay * (2 ** attempt), cap_delay)
                self._logger.warning(
                    "%s got %s on attempt %d, retrying in %.1fs",
                    self.source_id, resp.status_code, attempt + 1, delay,
                )
                time.sleep(delay)
                continue
            if resp.status_code >= 400:
                raise SourceClientError(
                    f"{self.source_id} HTTP {resp.status_code}: {resp.text[:400]}"
                )
            return resp

        raise SourceClientError(f"{self.source_id} max retries exceeded for {url}")

    def _cache_key(self, query: SourceQuery) -> str:
        payload = {
            "source_id": self.source_id,
            "ticker": query.ticker,
            "query_string": query.query_string,
            "lookback_days": query.lookback_days,
            "limit": query.limit,
            "sector_id": query.sector_id,
            "extra": dict(sorted(query.extra.items())),
        }
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _cache_path(self, query: SourceQuery) -> Path:
        return RAW_DIR / self.source_id / f"{self._cache_key(query)}.json"

    def _cached(self, query: SourceQuery) -> Optional[SourceResult]:
        path = self._cache_path(query)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self.cache_ttl_seconds:
            return None
        try:
            data = json.loads(path.read_text())
            docs = [
                SourceDocument(
                    source=d["source"],
                    source_id=d["source_id"],
                    url=d["url"],
                    content_hash=d["content_hash"],
                    doc_type=d["doc_type"],
                    title=d["title"],
                    published_at=datetime.fromisoformat(d["published_at"]) if d.get("published_at") else None,
                    fetched_at=datetime.fromisoformat(d["fetched_at"]),
                    raw_payload=d.get("raw_payload", {}),
                    summary=d.get("summary"),
                    entities_mentioned=d.get("entities_mentioned", []),
                )
                for d in data.get("documents", [])
            ]
            q_raw = data.get("query", {})
            q = SourceQuery(
                ticker=q_raw.get("ticker"),
                query_string=q_raw.get("query_string"),
                lookback_days=q_raw.get("lookback_days"),
                limit=q_raw.get("limit", 25),
                sector_id=q_raw.get("sector_id"),
                extra=q_raw.get("extra", {}),
            )
            return SourceResult(
                source=data["source"],
                query=q,
                documents=docs,
                fetched_at=datetime.fromisoformat(data["fetched_at"]),
                errors=data.get("errors", []),
            )
        except Exception as exc:
            self._logger.warning("Cache read failed for %s: %s", path, exc)
            return None

    def _cache(self, query: SourceQuery, result: SourceResult) -> None:
        path = self._cache_path(query)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")

        def _dt(dt: Optional[datetime]) -> Optional[str]:
            return dt.isoformat() if dt else None

        data = {
            "source": result.source,
            "query": {
                "ticker": query.ticker,
                "query_string": query.query_string,
                "lookback_days": query.lookback_days,
                "limit": query.limit,
                "sector_id": query.sector_id,
                "extra": query.extra,
            },
            "documents": [
                {
                    "source": d.source,
                    "source_id": d.source_id,
                    "url": d.url,
                    "content_hash": d.content_hash,
                    "doc_type": d.doc_type,
                    "title": d.title,
                    "published_at": _dt(d.published_at),
                    "fetched_at": _dt(d.fetched_at),
                    "raw_payload": d.raw_payload,
                    "summary": d.summary,
                    "entities_mentioned": d.entities_mentioned,
                }
                for d in result.documents
            ],
            "fetched_at": result.fetched_at.isoformat(),
            "errors": result.errors,
        }
        tmp.write_text(json.dumps(data, default=str))
        tmp.rename(path)

        self._persist_to_db(result)

    def _persist_to_db(self, result: SourceResult) -> None:
        if not self._db_session_factory:
            return
        try:
            from src.storage.models import Document
            with self._db_session_factory() as session:
                for doc in result.documents:
                    existing = session.query(Document).filter_by(
                        content_hash=doc.content_hash
                    ).first()
                    if existing:
                        continue
                    raw_path = str(self._cache_path(result.query)) if result.documents else None
                    row = Document(
                        source=doc.source,
                        source_id=doc.source_id,
                        url=doc.url,
                        content_hash=doc.content_hash,
                        doc_type=doc.doc_type,
                        title=doc.title[:1024] if doc.title else None,
                        published_at=doc.published_at,
                        fetched_at=doc.fetched_at,
                        raw_path=raw_path,
                    )
                    session.add(row)
                session.commit()
        except Exception as exc:
            self._logger.warning("DB persist failed: %s", exc)

    def _content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def _guard_available(self) -> None:
        if not self.is_available():
            raise SourceUnavailableError(
                f"{self.source_id} is not available (key env var {self.key_env_var} not set)"
            )
