"""Filesystem cache. Content is keyed by sha256 and partitioned by source name.

Layout:  data/raw/<source>/<hash>.<ext>

Used by source clients in Session 2; surface here so storage layer is self-contained.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.config import ROOT

CACHE_ROOT = ROOT / "data" / "raw"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cache_path(source: str, content_hash: str, ext: str = "json") -> Path:
    bucket = CACHE_ROOT / source
    bucket.mkdir(parents=True, exist_ok=True)
    return bucket / f"{content_hash}.{ext.lstrip('.')}"


def write_cache(source: str, data: bytes, ext: str = "json") -> tuple[str, Path]:
    h = sha256_bytes(data)
    p = cache_path(source, h, ext)
    if not p.exists():
        p.write_bytes(data)
    return h, p


def read_cache(source: str, content_hash: str, ext: str = "json") -> bytes | None:
    p = cache_path(source, content_hash, ext)
    return p.read_bytes() if p.exists() else None
