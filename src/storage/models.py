"""SQLAlchemy 2.x ORM models. ULID primary keys for sortability."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from ulid import ULID


def _ulid() -> str:
    return str(ULID())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    ticker: Mapped[str | None] = mapped_column(String(16), unique=True, nullable=True, index=True)
    cik: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    sector_id: Mapped[str] = mapped_column(String(64), index=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    is_watchlist: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    tier: Mapped[str | None] = mapped_column(String(1), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country: Mapped[str] = mapped_column(String(8), default="US")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    source: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    doc_type: Mapped[str] = mapped_column(String(32))  # filing|news|paper|patent|contract|other
    title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    raw_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (UniqueConstraint("company_id", "document_id", name="uq_mention"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    extracted_by: Mapped[str] = mapped_column(String(64))
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    cik: Mapped[str] = mapped_column(String(16))
    form_type: Mapped[str] = mapped_column(String(16))
    filing_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    summary: Mapped[str | None] = mapped_column(String, nullable=True)


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    headline: Mapped[str] = mapped_column(String(1024))
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    companies_mentioned: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class Fundamental(Base):
    __tablename__ = "fundamentals"
    __table_args__ = (Index("ix_fund_company_period", "company_id", "period", unique=True),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    period: Mapped[str] = mapped_column(String(8))  # YYYY-Q#
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    fcf: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_debt: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebitda: Mapped[float | None] = mapped_column(Float, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    source: Mapped[str] = mapped_column(String(64))


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(32))  # discover|analyse_doc|research
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    conviction_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recommendation_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    data_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sources_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("reports.id"), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    system_prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # success|fallback|failed
    reasoning_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DiscoveryScan(Base):
    __tablename__ = "discovery_scans"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lookback_quant_days: Mapped[int] = mapped_column(Integer, default=7)
    lookback_qual_days: Mapped[int] = mapped_column(Integer, default=14)
    candidates_surfaced: Mapped[int] = mapped_column(Integer, default=0)
    candidates_reported: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    brief_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
