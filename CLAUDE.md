# CLAUDE.md — VisionAiry2

## 1. Project purpose
Multi-agent research system that scans free public data sources, surfaces interesting companies in
technology / AI / robotics / batteries / materials / pharma / defence, and produces medium-depth
structured Markdown reports via multi-persona LLM analysis. API-only (no local ML weights).

## 2. Build state
- Session 1 — Foundation (config, storage, LLM client, CLI, key setup). **Complete.**
- Session 2 — Source clients (15+). **Pending.**
- Session 3 — Persona agents, Mode 1 discovery, Mode 3 doc analysis, report writer. **Pending.**
- Session 4 — FastAPI dashboard + tuning. **Pending.**

## 3. Disclaimer
> VisionAiry2 produces research aids, not financial or investment advice.
> All outputs may be confidently wrong. Free-tier APIs have rate limits and quality variance.
> Reports labelled "insufficient data" are working as designed. Independently verify every
> claim before any real-money decision. The author and contributors accept no liability
> for any decisions made on the basis of this software's output.

## 4. File structure
```
config.yaml              Single source of truth: sectors, watchlist, discovery params, llm_routing
.env                     Secrets (gitignored)
src/config.py            pydantic-settings loader; exposes get_config()
src/cli.py               typer CLI: setup-keys, validate-keys, init, ping, discover, analyse-doc
src/llm/client.py        complete(role, system, user) — looks up role in llm_routing, primary+fallback
src/llm/{deepseek,claude,gemini}.py   Thin provider adapters
src/llm/fallback.py      Retry/fallback policy (5xx, rate-limit, auth-error)
src/storage/db.py        SQLAlchemy engine, session factory, init_db()
src/storage/models.py    ORM models (companies, documents, mentions, filings, news_articles,
                         fundamentals, reports, agent_runs, discovery_scans)
src/storage/repositories.py   CompanyRepo, DocumentRepo, ReportRepo, AgentRunRepo
src/storage/files.py     Filesystem cache, sha256-keyed, partitioned by source
src/sources/             Source clients (Session 2)
src/agents/              Persona + workflow agents (Session 3)
src/modes/               Mode 1 (discovery), Mode 3 (doc analysis) drivers (Session 3)
src/reports/             Report writer + templates (Session 3)
src/dashboard/           FastAPI dashboard (Session 4)
scripts/init_db.py       Initialise SQLite + seed watchlist
scripts/seed_watchlist.py Idempotent watchlist seed
tests/smoke.py           Import + init + routing smoke tests
vendor/                  Read-only reference repos (gitignored). Never imported.
data/state.db            SQLite (gitignored)
data/raw/<source>/<sha>  Raw fetched documents (gitignored)
reports/<ticker>/<ts>/   Generated reports (established + real-ticker emerging)
reports/_emerging_pre_ipo_/<slug>/<ts>/  Pre-IPO / non-public entity reports (slug = lowercased entity name, special chars → "-")
digest/<date>.md         Daily briefs
```

## 5. Key constraints (must-never-violate)
1. Never hardcode API keys; always load via `src.config.get_config()`.
2. Never commit `.env`, `data/`, `reports/`, `digest/`, or `vendor/`.
3. No placeholders, TODOs, or "implement later" comments in finished code.
4. All model selection flows via `config.yaml` `llm_routing`; no hardcoded model IDs in agent code.
5. Always send the SEC `User-Agent` header (value from `$SEC_USER_AGENT`).
6. Discovery scans are single-process (SQLite is single-writer).
7. Use `uv add <pkg>` — never bare `pip install`.
8. Source clients must rate-limit, cache to disk, retry, and return a uniform schema.
9. Every LLM call logs a row to `agent_runs` (success or fallback).
10. Reports write to disk before the dashboard reads them.
11. `vendor/` is read-only inspiration; never import from it under `src/`.

## 6. How to run
```bash
uv sync
visionairy2 setup-keys      # paste keys; writes .env
visionairy2 validate-keys   # tests each key; rewires llm_routing fallbacks
visionairy2 init            # creates data/state.db + seeds watchlist
visionairy2 ping            # exercises every llm_routing role
```

## 7. Where logs and outputs go
- Reports → `reports/<ticker>/<timestamp>/`
- Briefs → `digest/<date>.md`
- Reasoning traces → `reports/<ticker>/<ts>/reasoning/<agent>.md`
- DB → `data/state.db`
- Raw cache → `data/raw/<source>/<hash>.{json|html|pdf}`
- Key status → `data/.key_status.json`
- Config audit → `data/.config_audit.log`

## 8. Known gotchas
1. SEC EDGAR requires a `User-Agent` on every request — never omit. Source: `$SEC_USER_AGENT`.
2. SEC EDGAR rate limit is 10 req/sec; `edgartools` enforces this — don't bypass.
3. Never hardcode API keys; load via `src/config.py`.
4. Never commit `data/`, `reports/`, `digest/`, `.env`, `vendor/`.
5. DeepSeek V4 Pro promo ends 2026-05-31 — keep model choice in `config.yaml`, swappable.
6. `yfinance` is a scraper, not an API — wrap in try/except, last-resort only.
7. macOS may need `xcode-select --install` for native deps.
8. SQLite is single-writer — no parallel discovery scans.
9. Use `uv add <pkg>`, not `pip install`.
10. `vendor/` repos are read-only design references; never import from them in `src/`.
11. `validate-keys` issues real (small) API calls; do not auto-run; confirm with user.
12. If a key fails validation, swap it out of `llm_routing` primary roles and log the change.

## 9. Session roadmap
- **Session 1** — Foundation (this session).
- **Session 2** — 15+ source clients.
- **Session 3** — Persona agents + Mode 1 + Mode 3 + report writer.
- **Session 4** — FastAPI dashboard + tuning.
- **v0.5** — Mode 2 deep research; Buffett/Munger personas.
- **v1** — Discord bot, scheduled cron, Postgres+pgvector.

## 10. Working with reference repos
- `vendor/ai-hedge-fund/` — Study persona prompt design (Wood, Druckenmiller, Burry, Lynch,
  Buffett). When writing `src/agents/personas/*.py` in Session 3, read theirs as inspiration but
  write our own.
- `vendor/finrobot/` — Study equity research report structure. When writing
  `src/reports/template.py` in Session 3, borrow section organisation but write our own prose.
- Do **not** import from `vendor/`. Do **not** install vendor packages. They are paper-only.
