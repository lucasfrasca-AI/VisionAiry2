"""Unit tests for all persona agents. All LLM calls are mocked."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.base import AgentInput, AgentOutput


def _make_input(ctx=None):
    return AgentInput(
        target="NVDA",
        context_data=ctx or {
            "ticker": "NVDA",
            "company_name": "NVIDIA Corporation",
            "sector_id": "ai_chips_compute",
            "fundamentals": {"revenue": 60922000000, "gross_margin": 0.745},
            "price": {"current_price": 875.0},
            "filings_recent": [
                {"title": "10-K 2024", "url": "https://sec.gov/1", "source": "edgar",
                 "doc_type": "filing", "summary": "Strong data center revenue", "raw_payload": {}}
            ],
            "news_recent": [
                {"title": "NVIDIA beats estimates", "url": "https://news.com/1",
                 "source": "marketaux", "doc_type": "news", "summary": "Q4 beat",
                 "published_at": "2025-01-01T00:00:00", "raw_payload": {}}
            ],
            "research_papers": [],
            "insider_transactions": [],
            "patents": [],
            "gov_contracts": [],
            "fda_actions": [],
            "macro_indicators": {},
            "tech_signal": [],
            "data_completeness": {},
        },
    )


def _mock_llm(return_json: dict):
    """Returns a mock complete_with_meta that yields (json_str, meta)."""
    meta = {"tokens_in": 100, "tokens_out": 200, "cost_usd": 0.001, "latency_ms": 500}
    return MagicMock(return_value=(json.dumps(return_json), meta))


# ─── Cathie Wood ─────────────────────────────────────────────────────────────

class TestCathieWoodAgent:
    def test_instantiates(self):
        from src.agents.personas.wood import CathieWoodAgent
        agent = CathieWoodAgent(llm_client=None)
        assert agent.agent_name == "wood"
        assert agent.llm_role == "persona_agents"

    def test_returns_valid_schema_with_full_context(self):
        from src.agents.personas.wood import CathieWoodAgent
        good_response = {
            "verdict": "STRONG_CONVICTION",
            "confidence": 0.85,
            "thesis_summary": "NVIDIA dominates AI compute infrastructure.",
            "innovation_score": 9,
            "tam_growth_view": "AI compute TAM growing >50%/year",
            "key_evidence": [{"claim": "Revenue up 206%", "source_ref": "filings_recent[0]"}],
            "what_would_change_my_mind": "If compute demand plateau materialises",
            "time_horizon_months": 36,
        }
        agent = CathieWoodAgent(llm_client=None)
        with patch("src.agents.personas.wood.CathieWoodAgent._call_llm",
                   return_value=(json.dumps(good_response), {"tokens_in": 100, "tokens_out": 200, "cost_usd": 0.001, "latency_ms": 300})):
            output = agent.run(_make_input())
        assert output.verdict == "STRONG_CONVICTION"
        assert output.confidence == 0.85
        assert len(output.citations) == 1
        assert output.tokens_in == 100

    def test_handles_insufficient_data(self):
        from src.agents.personas.wood import CathieWoodAgent
        agent = CathieWoodAgent(llm_client=None)
        with patch("src.agents.personas.wood.CathieWoodAgent._call_llm",
                   return_value=(json.dumps({"verdict": "INSUFFICIENT_DATA", "confidence": 0.0,
                       "thesis_summary": "", "innovation_score": 0, "tam_growth_view": "",
                       "key_evidence": [], "what_would_change_my_mind": "", "time_horizon_months": 0}),
                       {"tokens_in": 10, "tokens_out": 20, "cost_usd": 0.0001, "latency_ms": 100})):
            output = agent.run(_make_input({"ticker": "NVDA"}))
        assert output.verdict == "INSUFFICIENT_DATA"

    def test_handles_malformed_llm_response(self):
        from src.agents.personas.wood import CathieWoodAgent
        agent = CathieWoodAgent(llm_client=None)
        call_count = [0]

        def _bad_then_bad(system, user):
            call_count[0] += 1
            return ("not valid json at all {{{{", {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.0, "latency_ms": 50})

        with patch("src.agents.personas.wood.CathieWoodAgent._call_llm", side_effect=_bad_then_bad):
            output = agent.run(_make_input())
        assert output.verdict == "INSUFFICIENT_DATA"
        assert call_count[0] == 2  # tried twice

    def test_truncates_oversized_input(self):
        from src.agents.personas.wood import CathieWoodAgent
        big_ctx = _make_input().context_data.copy()
        big_news = [
            {"title": f"News {i}", "url": f"https://n.com/{i}", "source": "test",
             "doc_type": "news", "summary": "x" * 2000, "raw_payload": {"body": "y" * 5000}}
            for i in range(50)
        ]
        big_ctx["news_recent"] = big_news
        agent = CathieWoodAgent(llm_client=None)
        truncated = agent._truncate_context(big_ctx)
        json_size = len(json.dumps(truncated, default=str))
        assert json_size < len(json.dumps(big_ctx, default=str))


# ─── Stan Druckenmiller ───────────────────────────────────────────────────────

class TestStanDruckenmillerAgent:
    def test_instantiates(self):
        from src.agents.personas.druckenmiller import StanDruckenmillerAgent
        agent = StanDruckenmillerAgent(llm_client=None)
        assert agent.agent_name == "druckenmiller"

    def test_returns_valid_schema_with_full_context(self):
        from src.agents.personas.druckenmiller import StanDruckenmillerAgent
        good = {
            "verdict": "STARTER",
            "confidence": 0.7,
            "macro_setup": "Rising rates headwind but AI spending resilient",
            "asymmetry_ratio": 3.5,
            "primary_catalyst": "H100 demand acceleration",
            "thesis_break_event": "Fed hikes >100bp and hyperscalers cut capex",
            "key_evidence": [{"claim": "Data center rev up 150%", "source_ref": "filings_recent[0]"}],
            "time_horizon_months": 12,
        }
        agent = StanDruckenmillerAgent(llm_client=None)
        with patch("src.agents.personas.druckenmiller.StanDruckenmillerAgent._call_llm",
                   return_value=(json.dumps(good), {"tokens_in": 100, "tokens_out": 200, "cost_usd": 0.001, "latency_ms": 300})):
            output = agent.run(_make_input())
        assert output.verdict == "STARTER"
        assert output.parsed["asymmetry_ratio"] == 3.5

    def test_handles_insufficient_data(self):
        from src.agents.personas.druckenmiller import StanDruckenmillerAgent
        agent = StanDruckenmillerAgent(llm_client=None)
        insuf = {"verdict": "INSUFFICIENT_DATA", "confidence": 0.0,
                 "macro_setup": "", "asymmetry_ratio": 0.0, "primary_catalyst": "",
                 "thesis_break_event": "", "key_evidence": [], "time_horizon_months": 0}
        with patch("src.agents.personas.druckenmiller.StanDruckenmillerAgent._call_llm",
                   return_value=(json.dumps(insuf), {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.0, "latency_ms": 50})):
            output = agent.run(_make_input({"ticker": "X"}))
        assert output.verdict == "INSUFFICIENT_DATA"

    def test_handles_malformed_llm_response(self):
        from src.agents.personas.druckenmiller import StanDruckenmillerAgent
        agent = StanDruckenmillerAgent(llm_client=None)
        with patch("src.agents.personas.druckenmiller.StanDruckenmillerAgent._call_llm",
                   return_value=("garbage###", {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.0, "latency_ms": 50})):
            output = agent.run(_make_input())
        assert output.verdict == "INSUFFICIENT_DATA"

    def test_truncates_oversized_input(self):
        from src.agents.personas.druckenmiller import StanDruckenmillerAgent
        big_ctx = {**_make_input().context_data,
                   "news_recent": [{"title": f"N{i}", "raw_payload": {"x": "y" * 3000}} for i in range(40)]}
        agent = StanDruckenmillerAgent(llm_client=None)
        truncated = agent._truncate_context(big_ctx)
        assert len(json.dumps(truncated)) < len(json.dumps(big_ctx))


# ─── Michael Burry ────────────────────────────────────────────────────────────

class TestMichaelBurryAgent:
    def test_instantiates(self):
        from src.agents.personas.burry import MichaelBurryAgent
        agent = MichaelBurryAgent(llm_client=None)
        assert agent.agent_name == "burry"

    def test_returns_valid_schema_with_full_context(self):
        from src.agents.personas.burry import MichaelBurryAgent
        good = {
            "verdict": "AVOID",
            "confidence": 0.75,
            "bear_thesis": "Valuation 50x forward EPS unsustainable",
            "hidden_risks": ["Customer concentration top 3 = 45%"],
            "valuation_extreme_score": 8,
            "consensus_blind_spot": "Market ignoring competition from custom silicon",
            "key_evidence": [{"claim": "P/E 60x vs sector avg 25x", "source_ref": "fundamentals.pe_ratio"}],
            "what_would_make_me_long": "P/E compression to <20x with earnings intact",
        }
        agent = MichaelBurryAgent(llm_client=None)
        with patch("src.agents.personas.burry.MichaelBurryAgent._call_llm",
                   return_value=(json.dumps(good), {"tokens_in": 100, "tokens_out": 200, "cost_usd": 0.001, "latency_ms": 300})):
            output = agent.run(_make_input())
        assert output.verdict == "AVOID"
        assert output.parsed["valuation_extreme_score"] == 8

    def test_handles_insufficient_data(self):
        from src.agents.personas.burry import MichaelBurryAgent
        agent = MichaelBurryAgent(llm_client=None)
        with patch("src.agents.personas.burry.MichaelBurryAgent._call_llm",
                   return_value=(json.dumps({"verdict": "INSUFFICIENT_DATA", "confidence": 0.0,
                       "bear_thesis": "", "hidden_risks": [], "valuation_extreme_score": 0,
                       "consensus_blind_spot": "", "key_evidence": [], "what_would_make_me_long": ""}),
                       {"tokens_in": 5, "tokens_out": 5, "cost_usd": 0.0, "latency_ms": 30})):
            output = agent.run(_make_input({"ticker": "X"}))
        assert output.verdict == "INSUFFICIENT_DATA"

    def test_handles_malformed_llm_response(self):
        from src.agents.personas.burry import MichaelBurryAgent
        agent = MichaelBurryAgent(llm_client=None)
        with patch("src.agents.personas.burry.MichaelBurryAgent._call_llm",
                   return_value=("{invalid json", {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.0, "latency_ms": 50})):
            output = agent.run(_make_input())
        assert output.verdict == "INSUFFICIENT_DATA"

    def test_truncates_oversized_input(self):
        from src.agents.personas.burry import MichaelBurryAgent
        big_ctx = {**_make_input().context_data,
                   "filings_recent": [{"title": f"F{i}", "raw_payload": {"x": "z" * 4000}} for i in range(30)]}
        agent = MichaelBurryAgent(llm_client=None)
        truncated = agent._truncate_context(big_ctx)
        assert len(json.dumps(truncated)) < len(json.dumps(big_ctx))


# ─── Peter Lynch ──────────────────────────────────────────────────────────────

class TestPeterLynchAgent:
    def test_instantiates(self):
        from src.agents.personas.lynch import PeterLynchAgent
        agent = PeterLynchAgent(llm_client=None)
        assert agent.agent_name == "lynch"

    def test_returns_valid_schema_with_full_context(self):
        from src.agents.personas.lynch import PeterLynchAgent
        good = {
            "verdict": "BUY",
            "confidence": 0.7,
            "lynch_category": "fast grower",
            "business_clarity_score": 7,
            "peg_estimate": 0.8,
            "growth_sustainability": "Driven by structural AI compute demand shift",
            "key_evidence": [{"claim": "40% revenue CAGR last 3 years", "source_ref": "fundamentals.revenue"}],
            "time_horizon_months": 24,
        }
        agent = PeterLynchAgent(llm_client=None)
        with patch("src.agents.personas.lynch.PeterLynchAgent._call_llm",
                   return_value=(json.dumps(good), {"tokens_in": 100, "tokens_out": 200, "cost_usd": 0.001, "latency_ms": 300})):
            output = agent.run(_make_input())
        assert output.verdict == "BUY"
        assert output.parsed["peg_estimate"] == 0.8

    def test_handles_insufficient_data(self):
        from src.agents.personas.lynch import PeterLynchAgent
        agent = PeterLynchAgent(llm_client=None)
        with patch("src.agents.personas.lynch.PeterLynchAgent._call_llm",
                   return_value=(json.dumps({"verdict": "INSUFFICIENT_DATA", "confidence": 0.0,
                       "lynch_category": "", "business_clarity_score": 0,
                       "peg_estimate": None, "growth_sustainability": "",
                       "key_evidence": [], "time_horizon_months": 0}),
                       {"tokens_in": 5, "tokens_out": 5, "cost_usd": 0.0, "latency_ms": 30})):
            output = agent.run(_make_input({"ticker": "X"}))
        assert output.verdict == "INSUFFICIENT_DATA"

    def test_handles_malformed_llm_response(self):
        from src.agents.personas.lynch import PeterLynchAgent
        agent = PeterLynchAgent(llm_client=None)
        with patch("src.agents.personas.lynch.PeterLynchAgent._call_llm",
                   return_value=("---not json---", {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.0, "latency_ms": 50})):
            output = agent.run(_make_input())
        assert output.verdict == "INSUFFICIENT_DATA"

    def test_truncates_oversized_input(self):
        from src.agents.personas.lynch import PeterLynchAgent
        big_ctx = {**_make_input().context_data,
                   "research_papers": [{"title": f"P{i}", "summary": "s" * 2000, "raw_payload": {"x": "y" * 3000}} for i in range(20)]}
        agent = PeterLynchAgent(llm_client=None)
        truncated = agent._truncate_context(big_ctx)
        assert len(json.dumps(truncated)) < len(json.dumps(big_ctx))


# ─── Synthesis agents ──────────────────────────────────────────────────────────

class TestGapAnalysisAgent:
    def test_instantiates(self):
        from src.agents.synthesis.gap_analysis import GapAnalysisAgent
        agent = GapAnalysisAgent(llm_client=None)
        assert agent.agent_name == "gap_analysis"

    def test_returns_valid_schema(self):
        from src.agents.synthesis.gap_analysis import GapAnalysisAgent
        good = {
            "consensus_belief": "NVIDIA will grow 40% annually",
            "evidence_summary": "Revenue actually accelerating above consensus",
            "primary_gap": "Market underprices AI compute duration",
            "gap_direction": "UNDER_PRICED",
            "counterintuitive_argument": "Custom silicon threat is overstated near-term",
            "what_would_invalidate_consensus": "Hyperscalers announce capex cuts >20%",
            "persona_disagreement_summary": "Burry and Wood disagree on valuation",
            "key_evidence": [{"claim": "Data center rev beats", "source_ref": "filings_recent[0]"}],
            "confidence": 0.65,
        }
        agent = GapAnalysisAgent(llm_client=None)
        with patch("src.agents.synthesis.gap_analysis.GapAnalysisAgent._call_llm",
                   return_value=(json.dumps(good), {"tokens_in": 80, "tokens_out": 150, "cost_usd": 0.0005, "latency_ms": 200})):
            output = agent.run(AgentInput(target="NVDA", context_data={"ticker": "NVDA"}))
        assert output.verdict == "UNDER_PRICED"

    def test_handles_malformed_response(self):
        from src.agents.synthesis.gap_analysis import GapAnalysisAgent
        agent = GapAnalysisAgent(llm_client=None)
        with patch("src.agents.synthesis.gap_analysis.GapAnalysisAgent._call_llm",
                   return_value=("bad json", {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.0, "latency_ms": 50})):
            output = agent.run(AgentInput(target="X", context_data={}))
        assert output.verdict == "INSUFFICIENT_DATA"


class TestRiskInventoryAgent:
    def test_instantiates(self):
        from src.agents.synthesis.risk import RiskInventoryAgent
        agent = RiskInventoryAgent(llm_client=None)
        assert agent.agent_name == "risk_inventory"

    def test_returns_valid_schema(self):
        from src.agents.synthesis.risk import RiskInventoryAgent
        good = {
            "risks": [
                {"category": "concentration", "risk_statement": "Top 3 customers = 45% of revenue",
                 "severity": "HIGH", "evidence_ref": "filings_recent[0]", "mitigant": "Diversification underway"}
            ],
            "top_3_risks": ["Customer concentration"],
            "overall_risk_rating": "MEDIUM",
            "confidence": 0.7,
        }
        agent = RiskInventoryAgent(llm_client=None)
        with patch("src.agents.synthesis.risk.RiskInventoryAgent._call_llm",
                   return_value=(json.dumps(good), {"tokens_in": 80, "tokens_out": 150, "cost_usd": 0.0005, "latency_ms": 200})):
            output = agent.run(AgentInput(target="NVDA", context_data={"ticker": "NVDA"}))
        assert output.verdict == "MEDIUM"


class TestPortfolioManagerAgent:
    def test_instantiates(self):
        from src.agents.synthesis.portfolio_manager import PortfolioManagerAgent
        agent = PortfolioManagerAgent(llm_client=None)
        assert agent.agent_name == "portfolio_manager"

    def test_returns_valid_schema(self):
        from src.agents.synthesis.portfolio_manager import PortfolioManagerAgent
        good = {
            "recommendation": "STARTER",
            "conviction_level": "MEDIUM",
            "time_horizon_months": 18,
            "summary": "NVDA is a high-quality AI compute leader. Valuation is stretched but momentum strong. Risk is concentration and hyperscaler capex cuts.",
            "bull_case_one_liner": "AI spend accelerates through 2026",
            "bear_case_one_liner": "Custom silicon and macro headwinds compress margins",
            "persona_alignment": {"wood": "agrees", "druckenmiller": "agrees", "burry": "disagrees", "lynch": "neutral"},
            "thesis_breaks_if": "Hyperscaler capex falls >15% QoQ",
            "primary_evidence_for": ["Data center rev +206%", "Blackwell ramp on track"],
            "primary_evidence_against": ["P/E 60x", "Custom ASIC risk"],
            "confidence": 0.65,
        }
        agent = PortfolioManagerAgent(llm_client=None)
        with patch("src.agents.synthesis.portfolio_manager.PortfolioManagerAgent._call_llm",
                   return_value=(json.dumps(good), {"tokens_in": 200, "tokens_out": 300, "cost_usd": 0.002, "latency_ms": 500})):
            output = agent.run(AgentInput(target="NVDA", context_data={"ticker": "NVDA"}))
        assert output.verdict == "STARTER"
        assert output.parsed["conviction_level"] == "MEDIUM"
