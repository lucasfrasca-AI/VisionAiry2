"""Initialise the database and seed the watchlist."""

from __future__ import annotations

from scripts.seed_watchlist import seed
from src.storage.db import init_db


def main() -> None:
    init_db()
    n = seed()
    print(f"db initialised; {n} watchlist rows present")


if __name__ == "__main__":
    main()
