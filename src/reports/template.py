"""Report section structure and template rendering."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_OFF_SECTOR_GICS = frozenset({
    "communication services",
    "financial services",
    "consumer cyclical",
    "consumer staples",
    "consumer defensive",
    "real estate",
    "utilities",
})

REPORT_SECTIONS = [
    "executive_summary",
    "quantitative_snapshot",
    "qualitative_thesis",
    "multi_persona_debate",
    "gap_analysis",
    "risk_inventory",
    "recent_catalysts",
    "recommendation",
    "sources_used",
    "data_gaps",
]

PRE_IPO_REPORT_SECTIONS = [
    "executive_summary",
    "company_snapshot",
    "funding_and_validation_signals",
    "technology_product_description",
    "recent_catalysts",
    "why_it_surfaced",
    "milestones_to_watch",
    "sources_used",
    "what_we_could_not_find",
]


def render_draft(
    ticker: str,
    context: dict[str, Any],
    agent_outputs: dict[str, Any],
) -> str:
    wood = agent_outputs.get("wood", {})
    druck = agent_outputs.get("druckenmiller", {})
    burry = agent_outputs.get("burry", {})
    lynch = agent_outputs.get("lynch", {})
    gap = agent_outputs.get("gap_analysis", {})
    risk = agent_outputs.get("risk_inventory", {})
    pm = agent_outputs.get("portfolio_manager", {})

    company_name = context.get("company_name") or ticker
    sector_id = context.get("sector_id") or "unknown sector"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def _verdict(agent_dict: dict) -> str:
        v = agent_dict.get("parsed", {}).get("verdict") or agent_dict.get("verdict", "N/A")
        conf = agent_dict.get("confidence", 0.0)
        return f"{v} (confidence: {conf:.0%})"

    def _evidence_list(items: list) -> str:
        if not items:
            return "_No evidence cited._"
        return "\n".join(f"- {e.get('claim', '')} _(source: {e.get('source_ref', 'N/A')})_"
                         for e in items[:5])

    def _risk_rows(risks: list) -> str:
        if not risks:
            return "_No specific risks identified from available data._"
        rows = []
        for r in risks[:5]:
            sev = r.get("severity", "?")
            stmt = r.get("risk_statement", "")
            ref = r.get("evidence_ref", "N/A")
            mit = r.get("mitigant") or "None identified"
            rows.append(f"| {sev} | {r.get('category','?')} | {stmt} | {ref} | {mit} |")
        header = "| Severity | Category | Risk | Evidence | Mitigant |\n|---|---|---|---|---|"
        return header + "\n" + "\n".join(rows)

    def _news_catalysts(news: list) -> str:
        if not news:
            return "_No recent news available._"
        items = []
        for i, n in enumerate(news[:10]):
            title = n.get("title", "Untitled")
            src = n.get("source", "")
            url = n.get("url", "")
            date = n.get("published_at", "")[:10] if n.get("published_at") else ""
            link = f"[{title}]({url})" if url else title
            items.append(f"- {date} — {link} _(via {src})_")
        return "\n".join(items)

    def _source_list(
        news: list, filings: list, papers: list,
        ticker: str = "", company_name: str = "",
    ) -> tuple[str, int]:
        """Returns (rendered_source_list, n_dropped_papers)."""
        items = []
        idx = 1
        for n in (news or [])[:10]:
            url = n.get("url", "")
            title = n.get("title", "Untitled")
            src = n.get("source", "")
            items.append(f"{idx}. [{title}]({url}) — {src}")
            idx += 1
        for f in (filings or [])[:5]:
            url = f.get("url", "")
            title = f.get("title", "SEC Filing")
            items.append(f"{idx}. [{title}]({url}) — SEC EDGAR")
            idx += 1
        ticker_lower = ticker.lower()
        company_lower = company_name.lower() if company_name else ""
        dropped = 0
        for p in (papers or [])[:10]:
            url = p.get("url", "")
            title = p.get("title", "Research Paper")
            title_lower = title.lower()
            summary_lower = (p.get("summary") or "").lower()
            relevant = (
                (ticker_lower and (ticker_lower in title_lower or ticker_lower in summary_lower))
                or (company_lower and (company_lower in title_lower or company_lower in summary_lower))
            )
            if relevant:
                items.append(f"{idx}. [{title}]({url}) — arXiv/OpenAlex")
                idx += 1
            else:
                dropped += 1
        return ("\n".join(items) if items else "_No sources available._"), dropped

    fundamentals = context.get("fundamentals", {})
    price_data = context.get("price", {})
    completeness = context.get("data_completeness", {})

    # Pre-compute source list with paper filter
    sources_str, dropped_papers = _source_list(
        context.get("news_recent", []),
        context.get("filings_recent", []),
        context.get("research_papers", []),
        ticker=ticker,
        company_name=company_name,
    )

    # Sector mismatch banner
    company_sector_raw = (
        fundamentals.get("Sector") or fundamentals.get("sector") or
        fundamentals.get("SectorName") or fundamentals.get("sectorName") or ""
    )
    sector_mismatch_banner = ""
    if company_sector_raw and sector_id and company_sector_raw.lower() in _OFF_SECTOR_GICS:
        sector_mismatch_banner = (
            f"\n> **⚠ Sector mismatch:** Scan requested `{sector_id}`, "
            f"candidate primary sector is `{company_sector_raw}`. "
            "Surfaced as adjacent or via document-volume signal — not a core in-sector finding.\n"
        )

    fund_lines = []
    for k, v in list(fundamentals.items())[:12]:
        if v not in (None, "", [], {}):
            fund_lines.append(f"- **{k}**: {v}")

    price_lines = []
    for k, v in list(price_data.items())[:6]:
        if v not in (None, "", [], {}):
            price_lines.append(f"- **{k}**: {v}")

    pm_parsed = pm.get("parsed", {})
    pm_verdict = pm_parsed.get("recommendation", "INSUFFICIENT_DATA")
    pm_conviction = pm_parsed.get("conviction_level", "N/A")
    pm_horizon = pm_parsed.get("time_horizon_months", "N/A")
    pm_summary = pm_parsed.get("summary", pm.get("reasoning", ""))
    pm_thesis_break = pm_parsed.get("thesis_breaks_if", "Not defined")
    pm_bull = pm_parsed.get("bull_case_one_liner", "")
    pm_bear = pm_parsed.get("bear_case_one_liner", "")
    persona_align = pm_parsed.get("persona_alignment", {})

    gap_parsed = gap.get("parsed", {})
    risk_parsed = risk.get("parsed", {})

    wood_parsed = wood.get("parsed", {})
    druck_parsed = druck.get("parsed", {})
    burry_parsed = burry.get("parsed", {})
    lynch_parsed = lynch.get("parsed", {})

    missing_sources = [k for k, v in completeness.items() if "unavailable" in str(v) or "error" in str(v)]

    report = f"""# {company_name} ({ticker}) — Investment Research Report

**Generated:** {generated_at}
**Sector:** {sector_id}
**Recommendation:** {pm_verdict} | **Conviction:** {pm_conviction}
{sector_mismatch_banner}
> *This is a research aid, not financial advice. All claims require independent verification. Free-tier data sources may be incomplete or delayed.*

---

## 1. Executive Summary

{pm_summary or '_Insufficient data to generate summary._'}

**Bull case:** {pm_bull or '_N/A_'}
**Bear case:** {pm_bear or '_N/A_'}

---

## 2. Quantitative Snapshot

{''.join(fund_lines) or '_No fundamental data available._'}

**Price / Market Data:**
{''.join(price_lines) or '_No price data available._'}

---

## 3. Qualitative Thesis

**Wood (Innovation):** {wood_parsed.get('thesis_summary', '_N/A_')}

**Druckenmiller (Macro):** {druck_parsed.get('macro_setup', '_N/A_')}

**Lynch (Business Model):** {lynch_parsed.get('growth_sustainability', '_N/A_')}

---

## 4. Multi-Persona Debate

### Cathie Wood — {_verdict(wood)}
**Innovation Score:** {wood_parsed.get('innovation_score', 'N/A')}/10
**TAM View:** {wood_parsed.get('tam_growth_view', 'N/A')}
**What would change my mind:** {wood_parsed.get('what_would_change_my_mind', 'N/A')}

{_evidence_list(wood_parsed.get('key_evidence', []))}

### Stan Druckenmiller — {_verdict(druck)}
**Asymmetry Ratio:** {druck_parsed.get('asymmetry_ratio', 'N/A')}
**Primary Catalyst:** {druck_parsed.get('primary_catalyst', 'N/A')}
**Thesis Break Event:** {druck_parsed.get('thesis_break_event', 'N/A')}

{_evidence_list(druck_parsed.get('key_evidence', []))}

### Michael Burry — {_verdict(burry)}
**Valuation Extreme Score:** {burry_parsed.get('valuation_extreme_score', 'N/A')}/10
**Consensus Blind Spot:** {burry_parsed.get('consensus_blind_spot', 'N/A')}
**What would make me long:** {burry_parsed.get('what_would_make_me_long', 'N/A')}

{_evidence_list(burry_parsed.get('key_evidence', []))}

### Peter Lynch — {_verdict(lynch)}
**Category:** {lynch_parsed.get('lynch_category', 'N/A')}
**Business Clarity:** {lynch_parsed.get('business_clarity_score', 'N/A')}/10
**PEG Estimate:** {lynch_parsed.get('peg_estimate', 'N/A')}

{_evidence_list(lynch_parsed.get('key_evidence', []))}

---

## 5. GAP Analysis

**Consensus belief:** {gap_parsed.get('consensus_belief', '_N/A_')}

**Evidence shows:** {gap_parsed.get('evidence_summary', '_N/A_')}

**Primary gap:** {gap_parsed.get('primary_gap', '_N/A_')} — Direction: **{gap_parsed.get('gap_direction', 'N/A')}**

**Counterintuitive argument:** {gap_parsed.get('counterintuitive_argument', '_N/A_')}

**What would invalidate consensus:** {gap_parsed.get('what_would_invalidate_consensus', '_N/A_')}

**Persona disagreement:** {gap_parsed.get('persona_disagreement_summary', '_N/A_')}

---

## 6. Risk Inventory

**Overall risk rating:** {risk_parsed.get('overall_risk_rating', 'N/A')} (confidence: {risk_parsed.get('confidence', 0):.0%})

{_risk_rows(risk_parsed.get('risks', []))}

**Top 3 risks:**
{chr(10).join(f'- {r}' for r in risk_parsed.get('top_3_risks', [])) or '_None identified._'}

---

## 7. Recent Catalysts

{_news_catalysts(context.get('news_recent', []))}

---

## 8. Recommendation

| Field | Value |
|---|---|
| **Recommendation** | {pm_verdict} |
| **Conviction** | {pm_conviction} |
| **Time Horizon** | {pm_horizon} months |
| **Wood alignment** | {persona_align.get('wood', 'N/A')} |
| **Druckenmiller alignment** | {persona_align.get('druckenmiller', 'N/A')} |
| **Burry alignment** | {persona_align.get('burry', 'N/A')} |
| **Lynch alignment** | {persona_align.get('lynch', 'N/A')} |

**Thesis breaks if:** {pm_thesis_break}

**Primary evidence FOR:**
{chr(10).join(f'- {e}' for e in pm_parsed.get('primary_evidence_for', [])) or '_None._'}

**Primary evidence AGAINST:**
{chr(10).join(f'- {e}' for e in pm_parsed.get('primary_evidence_against', [])) or '_None._'}

---

## 9. Sources Used

{sources_str}

---

## 10. What We Could NOT Find

{chr(10).join(f'- **{k}**: {v}' for k, v in completeness.items() if 'unavailable' in str(v) or 'error' in str(v) or 'empty' in str(v)) or '_All configured sources returned data._'}

Missing or failed sources: {', '.join(missing_sources) if missing_sources else 'none'}

{f'_{dropped_papers} sector-context research paper(s) excluded from this source list as not directly relevant to {ticker}._' if dropped_papers else ''}
"""

    return report


def render_pre_ipo_draft(
    entity_name: str,
    context: dict[str, Any],
    agent_outputs: dict[str, Any],
) -> str:
    """Shorter 9-section template for pre-IPO / no-ticker emerging entities."""
    pm = agent_outputs.get("portfolio_manager", {})
    pm_parsed = pm.get("parsed", {})
    pm_summary = pm_parsed.get("summary", pm.get("reasoning", ""))

    sector_id = context.get("sector_id") or "unknown sector"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    completeness = context.get("data_completeness", {})

    gov_contracts = context.get("gov_contracts", [])
    news = context.get("news_recent", [])
    filings = context.get("filings_recent", [])

    def _contract_lines(contracts: list) -> str:
        if not contracts:
            return "_No government contract data retrieved._"
        lines = []
        for c in contracts[:5]:
            title = c.get("title", "")
            url = c.get("url", "")
            src = c.get("source", "")
            lines.append(f"- [{title}]({url}) _{src}_" if url else f"- {title} _{src}_")
        return "\n".join(lines)

    def _filing_lines(filings_list: list) -> str:
        if not filings_list:
            return "_No recent filings found._"
        lines = []
        for f in filings_list[:5]:
            title = f.get("title", "SEC Filing")
            url = f.get("url", "")
            lines.append(f"- [{title}]({url})" if url else f"- {title}")
        return "\n".join(lines)

    def _news_lines(news_list: list) -> str:
        if not news_list:
            return "_No recent news found._"
        lines = []
        for n in news_list[:6]:
            title = n.get("title", "Untitled")
            url = n.get("url", "")
            date = (n.get("published_at") or "")[:10]
            lines.append(f"- {date} — [{title}]({url})" if url else f"- {date} — {title}")
        return "\n".join(lines)

    # Emerging signal sources that produced docs for this entity
    all_docs = (
        context.get("gov_contracts", [])
        + context.get("filings_recent", [])
        + context.get("news_recent", [])
        + context.get("research_papers", [])
    )
    signal_sources = sorted({d.get("source", "") for d in all_docs if d.get("source")})

    missing_sources = [k for k, v in completeness.items()
                       if "unavailable" in str(v) or "error" in str(v) or "empty" in str(v)]

    # IPO/time horizon hint from PM output
    time_horizon = pm_parsed.get("time_horizon_months")
    if time_horizon:
        horizon_str = f"{time_horizon} months"
    elif any("ipo" in (d.get("title") or "").lower() for d in filings):
        horizon_str = "12–24 months (IPO-stage signals present)"
    else:
        horizon_str = "24–60 months (early-stage signals only)"

    report = f"""# {entity_name} — Emerging Entity Research Brief

**Generated:** {generated_at}
**Sector:** {sector_id}
**Recommendation:** WATCHLIST | **Conviction:** LOW | **Time Horizon:** {horizon_str}

> *Pre-IPO / non-public entity. Fundamental and price data unavailable. This is a research aid, not financial advice.*

---

## 1. Executive Summary

{pm_summary or '_Insufficient data to generate summary. Entity surfaced via government contract/grant signals only._'}

---

## 2. Company Snapshot

**Entity Name:** {entity_name}
**Sector context:** {sector_id}
**Public market status:** Pre-IPO / not publicly traded (no ticker resolved)
**Known details:** See government contract and filing records below.

---

## 3. Funding & Validation Signals

{_contract_lines(gov_contracts)}

**Recent filings:**
{_filing_lines(filings)}

---

## 4. Technology / Product Description

{pm_parsed.get('bull_case_one_liner') or '_No product description extracted. Review raw contract/grant abstracts in data.json._'}

---

## 5. Recent Catalysts

{_news_lines(news)}

---

## 6. Why It Surfaced

**Signal sources:** {', '.join(signal_sources) if signal_sources else '_unknown_'}

{pm_parsed.get('thesis_breaks_if') or '_No additional surfacing rationale available._'}

---

## 7. Milestones to Watch

- Monitor for S-1 / IPO filing if signals progress
- Track follow-on government contract awards
- Watch for Series B/C funding announcements in press
- **Time horizon estimate:** {horizon_str}

---

## 8. Sources Used

{chr(10).join(f'- {s}' for s in signal_sources) if signal_sources else '_No sources resolved._'}

---

## 9. What We Could Not Find

{chr(10).join(f'- **{k}**: {v}' for k, v in completeness.items() if 'unavailable' in str(v) or 'error' in str(v) or 'empty' in str(v)) or '_No notable gaps._'}

Missing or failed sources: {', '.join(missing_sources) if missing_sources else 'none'}
"""

    return report
