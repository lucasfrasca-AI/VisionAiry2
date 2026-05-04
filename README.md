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

### Run discovery scan (after Session 3)
```bash
visionairy2 discover
```

### View dashboard (after Session 4)
```bash
./scripts/run_dashboard.sh
# Open http://localhost:8000
```

## Build state

- **Session 1 (foundation)** — config, storage, LLM client, CLI skeleton, key validation. ✅
- Session 2 — source clients (SEC, news, papers, patents, etc.). Pending.
- Session 3 — agents, Mode 1 discovery, Mode 3 doc analysis, report writer. Pending.
- Session 4 — FastAPI dashboard + tuning. Pending.

See [CLAUDE.md](CLAUDE.md) for architecture, constraints, and gotchas.
