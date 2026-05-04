"""Smoke tests for Session 1 foundation.

These verify the foundation is wired correctly without making real API calls.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def test_imports_all_modules():
    import src.cli  # noqa
    import src.config  # noqa
    import src.llm.claude  # noqa
    import src.llm.client  # noqa
    import src.llm.deepseek  # noqa
    import src.llm.fallback  # noqa
    import src.llm.gemini  # noqa
    import src.storage.db  # noqa
    import src.storage.files  # noqa
    import src.storage.models  # noqa
    import src.storage.repositories  # noqa


def test_config_loads():
    from src.config import reload_config
    cfg = reload_config()
    assert len(cfg.sectors) >= 18, f"expected >=18 sectors, got {len(cfg.sectors)}"
    assert "entity_extraction" in cfg.llm_routing
    assert "report_writer" in cfg.llm_routing
    assert "escalation" in cfg.llm_routing
    assert cfg.discovery.top_n == 7


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # Force config + engine to re-init with the override
    import src.config as config_mod
    import src.storage.db as db_mod
    config_mod.get_config.cache_clear()
    db_mod._engine_singleton = None
    db_mod._session_factory = None
    yield db_path
    db_mod._engine_singleton = None
    db_mod._session_factory = None


def test_init_db_and_seed(tmp_db):
    from scripts.seed_watchlist import seed
    from src.storage.db import init_db, session_scope
    from src.storage.repositories import CompanyRepo

    init_db()
    n = seed()
    assert n > 0
    with session_scope() as s:
        repo = CompanyRepo(s)
        assert repo.count() > 0


def test_seed_is_idempotent(tmp_db):
    from scripts.seed_watchlist import seed
    from src.storage.db import init_db, session_scope
    from src.storage.repositories import CompanyRepo

    init_db()
    n1 = seed()
    n2 = seed()
    assert n1 == n2  # same number of upsert ops both times
    with session_scope() as s:
        first_count = CompanyRepo(s).count()
    seed()
    with session_scope() as s:
        second_count = CompanyRepo(s).count()
    assert first_count == second_count  # no duplicate rows


def test_llm_client_routes_correctly(tmp_db):
    """Mocked: verify complete(role=...) selects the right adapter and logs."""
    from src.storage.db import init_db, session_scope
    from src.storage.models import AgentRun
    from src.llm import client as llm_client

    init_db()

    # Mock each adapter's complete()
    def fake_complete(*, model, system, user, max_tokens, temperature):
        return f"answer-from-{model}", {"input_tokens": 1, "output_tokens": 1}

    with patch("src.llm.deepseek.complete", side_effect=fake_complete) as ds, \
         patch("src.llm.claude.complete", side_effect=fake_complete) as cl, \
         patch("src.llm.gemini.complete", side_effect=fake_complete) as gm:
        # entity_extraction → deepseek
        text = llm_client.complete(role="entity_extraction", system="s", user="u")
        assert text.startswith("answer-from-")
        assert ds.call_count == 1

        # report_writer → anthropic
        llm_client.complete(role="report_writer", system="s", user="u")
        assert cl.call_count == 1

        # document_summary → gemini
        llm_client.complete(role="document_summary", system="s", user="u")
        assert gm.call_count == 1

    with session_scope() as s:
        runs = s.query(AgentRun).all()
        assert len(runs) >= 3
        assert all(r.status == "success" for r in runs)


def test_fallback_triggers_on_primary_failure(tmp_db):
    from src.llm import client as llm_client
    from src.llm.fallback import call_with_fallback

    from src.storage.db import init_db
    init_db()

    def boom():
        raise TimeoutError("simulated 504")

    def good():
        return "ok-from-fallback", {"input_tokens": 1, "output_tokens": 1}

    text, _, status = call_with_fallback(boom, good)
    assert status == "fallback"
    assert "fallback" in text


def test_fuzzy_map_parses_pasted_block():
    from src.cli import _parse_pasted_block

    block = """
    # comment line
    anthropic = sk-ant-XXXX
    deepseek: sk-deepseek-YYY
    Gemini sk-gemini-ZZZ
    UNKNOWN_FAKE=whatever
    """
    canonical, unknown = _parse_pasted_block(block)
    assert canonical["ANTHROPIC_API_KEY"] == "sk-ant-XXXX"
    assert canonical["DEEPSEEK_API_KEY"] == "sk-deepseek-YYY"
    assert canonical["GEMINI_API_KEY"] == "sk-gemini-ZZZ"
    assert "UNKNOWN_FAKE" in unknown
