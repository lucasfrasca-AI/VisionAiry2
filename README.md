# VisionAiry2

Multi-agent research system that scans free public data sources, surfaces interesting companies in
technology / AI / robotics / batteries / materials / pharma / defence, and produces medium-depth
structured Markdown reports via multi-persona LLM analysis.

> **DISCLAIMER**: VisionAiry2 produces research aids, not financial or investment advice.
> All outputs may be confidently wrong. Free-tier APIs have rate limits and quality variance.
> Reports labelled "insufficient data" are working as designed. Independently verify every
> claim before any real-money decision. The author and contributors accept no liability
> for any decisions made on the basis of this software's output.

## Quickstart

### First-time setup
```bash
git clone https://github.com/lucasfrasca-AI/VisionAiry2.git
cd VisionAiry2
uv sync
visionairy2 setup-keys      # paste your API keys when prompted
visionairy2 validate-keys   # tests every key, configures fallbacks
visionairy2 init            # initialises database + seeds watchlist
visionairy2 ping            # confirms LLM routing works end-to-end
```

### Run a discovery scan
```bash
visionairy2 discover --sectors ai_chips_compute --top-n 5
```

### Launch the dashboard
```bash
./scripts/run_dashboard.sh
# Open http://localhost:8000
```

## Dashboard

The dashboard is a read-only FastAPI/Jinja2 UI that surfaces reports, briefs, source health,
and watchlist status. All actions (discovery, doc analysis) run from the CLI.

### Launch
```bash
./scripts/run_dashboard.sh
```
Open http://localhost:8000 in your browser. The server binds to `127.0.0.1:8000` only.
No authentication — localhost-only tool.

### Routes

| Route | Description |
|---|---|
| `/` | Home — latest report cards (both tracks) + daily brief preview + stats |
| `/reports` | All reports, filterable by track / sector / recommendation, paginated |
| `/reports/emerging` | Pre-IPO and entity-name reports only |
| `/reports/{TICKER}/{timestamp}` | Established report detail — full markdown, persona verdicts, Plotly price chart |
| `/reports/emerging/{slug}/{timestamp}` | Pre-IPO report detail — markdown, "Why It Surfaced" signals, agent reasoning |
| `/digest` | List of daily briefs |
| `/digest/{YYYY-MM-DD}` | Individual brief detail with referenced-ticker sidebar |
| `/sources` | Source health — API key status, doc counts, validation command |
| `/watchlist` | All watchlist companies grouped by sector, with last-report status |

### Two-track report system

**Established track** (`reports/<TICKER>/<timestamp>/`):
- Public companies with real ticker symbols (AMD, GOOGL, DJT)
- Full 10-section report: executive summary, quantitative snapshot, multi-persona debate, risk inventory, recommendation
- Four analyst personas (Wood, Druckenmiller, Burry, Lynch) with distinct voices
- Plotly mini price chart on report detail page

**Pre-IPO / Emerging track** (`reports/_emerging_pre_ipo_/<slug>/<timestamp>/`):
- Non-public entities surfaced via SBIR grants, S-1 filings, sub-award contracts, IPO calendars
- Lean 9-section report: funding signals, why it surfaced, milestones to watch
- Default recommendation: WATCHLIST / LOW
- No price chart (no ticker available)
- Identified by slugified entity name (e.g. `cpi-satcom-antenna-technologies-inc`)

### Recommendation badges

| Badge | Colour | Meaning |
|---|---|---|
| CORE | Green | High-conviction long; conviction level varies |
| STARTER | Blue | Worth a starter position; monitor closely |
| WATCHLIST | Amber | Interesting but not actionable yet |
| AVOID | Red | Risk/reward unfavourable at current price |
| INSUFFICIENT_DATA | Grey | Not enough data to form a view |

### Track badges

| Badge | Colour | Meaning |
|---|---|---|
| EST | Grey | Established public company |
| PRE-IPO | Sky blue | Emerging / non-public entity |

### Conviction levels
`HIGH` → `MEDIUM` → `LOW` — displayed alongside the recommendation badge.

### Notes
- Dashboard is **read-only**. No actions (discovery, watchlist edits) can be triggered from it.
- Reports auto-written to disk by CLI; dashboard reads them. No live sync — 60s meta-refresh on home/digest pages.
- Plotly price chart loads only on established report detail pages (~1MB bundle, lazy-loaded).
- Path traversal is rejected server-side; ticker/slug identifiers are validated with strict regex.

## Build state

- **Session 1 (foundation)** — config, storage, LLM client, CLI skeleton, key validation. ✅
- **Session 2 (sources)** — 27+ source clients (SEC, news, research papers, patents, gov contracts, etc.). ✅
- **Session 3 (agents + modes)** — 4 persona agents, synthesis agents, Mode 1 discovery, Mode 3 doc analysis, report writer. ✅
- **Session 4 (dashboard)** — FastAPI dashboard with dual-track support, all 8 routes, smoke tests. ✅

See [CLAUDE.md](CLAUDE.md) for architecture, constraints, and gotchas.
