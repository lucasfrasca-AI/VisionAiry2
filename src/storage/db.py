"""Engine + session factory + init_db()."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_config
from src.storage.models import Base


def _engine():
    cfg = get_config()
    url = cfg.secrets.DATABASE_URL
    if url.startswith("sqlite:///"):
        relative = url.replace("sqlite:///", "", 1)
        path = Path(relative)
        if not path.is_absolute():
            from src.config import ROOT
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
    return create_engine(url, future=True)


_engine_singleton = None
_session_factory = None


def get_engine():
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = _engine()
    return _engine_singleton


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    sf = get_session_factory()
    s = sf()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db() -> None:
    """Create all tables. Idempotent."""
    Base.metadata.create_all(get_engine())
