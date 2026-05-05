"""Dashboard route smoke tests — no real LLM calls, no shared filesystem."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import app

client = TestClient(app, raise_server_exceptions=True)

_AMD_TS = "20260101T120000Z"
_SLUG_TS = "20260101T120000Z"
_SLUG = "test-entity-inc"


def _make_report_dir(base: Path, rec: str = "WATCHLIST") -> Path:
    ts_dir = base / _AMD_TS
    ts_dir.mkdir(parents=True, exist_ok=True)
    (ts_dir / "report.md").write_text(
        f"# Test — Report\n\n**Generated:** 2026-01-01 12:00 UTC\n"
        f"**Sector:** test_sector\n"
        f"**Recommendation:** {rec} | **Conviction:** LOW\n\n"
        "Content here.\n"
    )
    (ts_dir / "cost.json").write_text(json.dumps({"total_usd": 0.01, "per_agent": {}}))
    (ts_dir / "data.json").write_text(json.dumps({}))
    (ts_dir / "sources.json").write_text(json.dumps([]))
    return ts_dir


# ── Monkeypatching helpers ────────────────────────────────────────────────────

def _patch_roots(monkeypatch, tmp_path):
    monkeypatch.setattr("src.dashboard.data._REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setattr("src.dashboard.data._PRE_IPO_ROOT", tmp_path / "reports" / "_emerging_pre_ipo_")
    monkeypatch.setattr("src.dashboard.data._DIGEST_ROOT", tmp_path / "digest")
    monkeypatch.setattr("src.dashboard.data._KEY_STATUS_PATH", tmp_path / "data" / ".key_status.json")


# ── Home page tests ───────────────────────────────────────────────────────────

def test_home_returns_200_with_no_reports(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "digest").mkdir(parents=True, exist_ok=True)
    r = client.get("/")
    assert r.status_code == 200
    assert "VisionAiry2" in r.text


def test_home_returns_200_with_reports(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    _make_report_dir(tmp_path / "reports" / "AMD", rec="AVOID")
    (tmp_path / "digest").mkdir(parents=True, exist_ok=True)
    r = client.get("/")
    assert r.status_code == 200
    assert "AMD" in r.text


def test_home_returns_200_with_emerging_report(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    _make_report_dir(tmp_path / "reports" / "_emerging_pre_ipo_" / _SLUG, rec="WATCHLIST")
    (tmp_path / "digest").mkdir(parents=True, exist_ok=True)
    r = client.get("/")
    assert r.status_code == 200
    assert "PRE-IPO" in r.text


# ── Established report detail ─────────────────────────────────────────────────

def test_established_report_detail_returns_full_view(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    _make_report_dir(tmp_path / "reports" / "AMD", rec="AVOID")
    r = client.get(f"/reports/AMD/{_AMD_TS}")
    assert r.status_code == 200
    assert "AMD" in r.text
    assert "AVOID" in r.text


def test_report_detail_404_on_missing(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    r = client.get(f"/reports/AMD/{_AMD_TS}")
    assert r.status_code == 404


# ── Emerging report detail ────────────────────────────────────────────────────

def test_emerging_report_detail_returns_full_view(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    _make_report_dir(tmp_path / "reports" / "_emerging_pre_ipo_" / _SLUG, rec="WATCHLIST")
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    r = client.get(f"/reports/emerging/{_SLUG}/{_SLUG_TS}")
    assert r.status_code == 200
    assert "WATCHLIST" in r.text


# ── Path traversal protection ─────────────────────────────────────────────────

def test_path_traversal_rejected(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    r = client.get(f"/reports/../etc/passwd/{_AMD_TS}")
    assert r.status_code in (404, 422)


def test_path_traversal_rejected_established_bad_ticker(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    r = client.get(f"/reports/TOOLONGTICKER/{_AMD_TS}")
    assert r.status_code == 404


def test_path_traversal_rejected_emerging(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    r = client.get(f"/reports/emerging/UPPERCASE_BAD/{_SLUG_TS}")
    assert r.status_code == 404


# ── List views ────────────────────────────────────────────────────────────────

def test_reports_list_returns_200(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    r = client.get("/reports")
    assert r.status_code == 200


def test_emerging_list_returns_200(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    r = client.get("/reports/emerging")
    assert r.status_code == 200
    assert "Pre-IPO" in r.text


def test_sources_view_returns_200(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    key_dir = tmp_path / "data"
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / ".key_status.json").write_text(json.dumps({
        "checked_at": "2026-01-01T00:00:00+00:00",
        "statuses": {
            "ANTHROPIC_API_KEY": {"status": "WORKING", "notes": "ok"},
            "DEEPSEEK_API_KEY": {"status": "INVALID", "notes": "bad key"},
        }
    }))
    r = client.get("/sources")
    assert r.status_code == 200
    assert "WORKING" in r.text


def test_watchlist_view_returns_200(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    # list_watchlist() will fail DB query gracefully and return []
    r = client.get("/watchlist")
    assert r.status_code == 200


def test_digest_view_404_on_bad_date_format(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    r = client.get("/digest/not-a-date")
    assert r.status_code == 404


def test_digest_list_returns_200(monkeypatch, tmp_path):
    _patch_roots(monkeypatch, tmp_path)
    (tmp_path / "digest").mkdir(parents=True, exist_ok=True)
    r = client.get("/digest")
    assert r.status_code == 200
