"""Idempotent watchlist seed. Reads config.yaml watchlist, upserts companies."""

from __future__ import annotations

from src.config import get_config
from src.storage.db import session_scope
from src.storage.repositories import CompanyRepo


def seed() -> int:
    cfg = get_config()
    inserted_or_updated = 0
    with session_scope() as s:
        repo = CompanyRepo(s)
        for sector_id, entries in cfg.watchlist.items():
            for entry in entries:
                repo.upsert(
                    ticker=entry.ticker,
                    name=entry.ticker,  # placeholder; resolved by source clients in Session 2
                    sector_id=sector_id,
                    is_watchlist=True,
                    tier=entry.tier,
                )
                inserted_or_updated += 1
    return inserted_or_updated


if __name__ == "__main__":
    n = seed()
    print(f"seeded/updated {n} watchlist entries")
