"""Repository helpers — minimal CRUD for tables exercised in Session 1.

Heavier query logic lands in Sessions 2/3. These exist now so smoke tests and
the LLM client's agent_runs logging have a stable surface to call.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import AgentRun, Company, Document, Report


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CompanyRepo:
    def __init__(self, session: Session):
        self.s = session

    def upsert(
        self,
        *,
        ticker: str | None,
        name: str,
        sector_id: str,
        is_watchlist: bool = False,
        tier: str | None = None,
        cik: str | None = None,
        is_public: bool = True,
        exchange: str | None = None,
        country: str = "US",
    ) -> Company:
        existing = None
        if ticker:
            existing = self.s.scalar(select(Company).where(Company.ticker == ticker))
        if existing:
            existing.name = name
            existing.sector_id = sector_id
            existing.is_watchlist = is_watchlist
            existing.tier = tier
            if cik is not None:
                existing.cik = cik
            existing.exchange = exchange
            existing.country = country
            return existing
        c = Company(
            ticker=ticker,
            name=name,
            sector_id=sector_id,
            is_watchlist=is_watchlist,
            tier=tier,
            cik=cik,
            is_public=is_public,
            exchange=exchange,
            country=country,
        )
        self.s.add(c)
        return c

    def count(self) -> int:
        from sqlalchemy import func
        return self.s.scalar(select(func.count(Company.id))) or 0

    def all_watchlist(self) -> list[Company]:
        return list(self.s.scalars(select(Company).where(Company.is_watchlist.is_(True))))


class DocumentRepo:
    def __init__(self, session: Session):
        self.s = session

    def get_by_hash(self, content_hash: str) -> Document | None:
        return self.s.scalar(select(Document).where(Document.content_hash == content_hash))

    def add(self, **kwargs: Any) -> Document:
        d = Document(**kwargs)
        self.s.add(d)
        return d


class ReportRepo:
    def __init__(self, session: Session):
        self.s = session

    def add(self, **kwargs: Any) -> Report:
        r = Report(**kwargs)
        self.s.add(r)
        return r


class AgentRunRepo:
    def __init__(self, session: Session):
        self.s = session

    def log(
        self,
        *,
        agent_name: str,
        role: str,
        model: str,
        provider: str,
        status: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_estimate: float | None = None,
        latency_ms: int | None = None,
        report_id: str | None = None,
        system_prompt_hash: str | None = None,
        reasoning_path: str | None = None,
        started_at: datetime | None = None,
    ) -> AgentRun:
        run = AgentRun(
            agent_name=agent_name,
            role=role,
            model=model,
            provider=provider,
            status=status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate=cost_estimate,
            latency_ms=latency_ms,
            report_id=report_id,
            system_prompt_hash=system_prompt_hash,
            reasoning_path=reasoning_path,
            started_at=started_at or _utcnow(),
            finished_at=_utcnow(),
        )
        self.s.add(run)
        return run
