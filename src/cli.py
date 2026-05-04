"""Typer CLI for VisionAiry2.

Commands:
  setup-keys      Paste a block of keys; writes/updates .env with fuzzy-mapped names.
  validate-keys   Runs minimal-cost validation per key, rewires llm_routing fallbacks.
  init            Initialises database + seeds watchlist.
  ping            Exercises every llm_routing role; prints which routes work.
  discover        Stub (Mode 1 — Session 3).
  analyse-doc     Stub (Mode 3 — Session 3).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import typer
import yaml
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from dotenv import load_dotenv
from src.config import ROOT, CONFIG_YAML_PATH, ENV_PATH, get_config, reload_config

# Inject .env into os.environ so source clients can read keys via os.environ.get()
load_dotenv(ENV_PATH, override=False)

app = typer.Typer(add_completion=False, no_args_is_help=True, help="VisionAiry2 CLI.")
console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Fuzzy map: user-supplied names → canonical .env names
# ─────────────────────────────────────────────────────────────────────────────
FUZZY_MAP: dict[str, str] = {
    # LLM
    "anthropic": "ANTHROPIC_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
    "google_api_key": "GEMINI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    # Search / retrieval
    "tavily": "TAVILY_API_KEY",
    "tavily_api_key": "TAVILY_API_KEY",
    "firecrawl": "FIRECRAWL_API_KEY",
    "firecrawl_api_key": "FIRECRAWL_API_KEY",
    "exa": "EXA_API_KEY",
    "serper": "SERPER_API_KEY",
    # Financial
    "finnhub": "FINNHUB_API_KEY",
    "finnhub_api_key": "FINNHUB_API_KEY",
    "fmp": "FMP_API_KEY",
    "financialmodelingprep": "FMP_API_KEY",
    "financial_modeling_prep": "FMP_API_KEY",
    "fmp_api_key": "FMP_API_KEY",
    "financialdatasets": "FINANCIAL_DATASETS_API_KEY",
    "financial_datasets": "FINANCIAL_DATASETS_API_KEY",
    "findata": "FINANCIAL_DATASETS_API_KEY",
    "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
    "alphavantage": "ALPHA_VANTAGE_API_KEY",
    "av": "ALPHA_VANTAGE_API_KEY",
    # News
    "guardian": "GUARDIAN_API_KEY",
    "the_guardian": "GUARDIAN_API_KEY",
    "marketaux": "MARKETAUX_API_KEY",
    "newsapi": "NEWSAPI_KEY",
    "news_api": "NEWSAPI_KEY",
    "newsdata": "NEWSDATA_API_KEY",
    # Macro / specialist / research
    "fred": "FRED_API_KEY",
    "openfda": "OPENFDA_API_KEY",
    "fda": "OPENFDA_API_KEY",
    "uspto": "USPTO_API_KEY",
    "patentsview": "USPTO_API_KEY",
    "eia": "EIA_API_KEY",
    "sam": "SAM_GOV_API_KEY",
    "sam_gov": "SAM_GOV_API_KEY",
    "samgov": "SAM_GOV_API_KEY",
    "github": "GITHUB_TOKEN",
    "gh": "GITHUB_TOKEN",
    "github_token": "GITHUB_TOKEN",
    "semantic_scholar": "SEMANTIC_SCHOLAR_API_KEY",
    "semantischolar": "SEMANTIC_SCHOLAR_API_KEY",
    "s2": "SEMANTIC_SCHOLAR_API_KEY",
    "core": "CORE_API_KEY",
    "core_api": "CORE_API_KEY",
    "pubmed": "NCBI_API_KEY",
    "ncbi": "NCBI_API_KEY",
    "stocktwits": "STOCKTWITS_API_KEY",
    # Default identity
    "sec_user_agent": "SEC_USER_AGENT",
}

DEFAULT_SEC_USER_AGENT = "VisionAiry2 projectgemini53@gmail.com"


def _norm(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def _parse_pasted_block(block: str) -> tuple[dict[str, str], list[str]]:
    """Returns (canonical_kv, unrecognised_names)."""
    canonical: dict[str, str] = {}
    unknown: list[str] = []
    for line in block.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # Accept: KEY=VAL  KEY = VAL  KEY: VAL  KEY VAL
        m = re.match(r"^([A-Za-z0-9_\-\.]+)\s*[:= ]\s*(.+)$", s)
        if not m:
            continue
        raw_key, raw_val = m.group(1), m.group(2).strip().strip('"').strip("'")
        nk = _norm(raw_key)
        canonical_name = FUZZY_MAP.get(nk)
        if canonical_name is None:
            # also try the raw uppercase form (e.g. user pasted "ANTHROPIC_API_KEY=...")
            up = raw_key.strip().upper()
            if up in {v for v in FUZZY_MAP.values()}:
                canonical_name = up
        if canonical_name is None:
            unknown.append(raw_key)
            continue
        canonical[canonical_name] = raw_val
    return canonical, unknown


def _read_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _write_env(values: dict[str, str]) -> None:
    """Write .env preserving order: existing keys keep position, new keys appended.
    Comments-only lines are preserved by reading from .env.example template if .env is fresh."""
    if ENV_PATH.exists():
        original = ENV_PATH.read_text().splitlines()
    else:
        example = ROOT / ".env.example"
        original = example.read_text().splitlines() if example.exists() else []

    out_lines: list[str] = []
    seen: set[str] = set()
    for line in original:
        s = line.rstrip()
        m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=", s)
        if m:
            key = m.group(1)
            new_val = values.get(key, "")
            inline_comment = ""
            if "#" in s:
                # preserve trailing comment if present in original
                eq = s.index("=")
                tail = s[eq + 1 :]
                if "#" in tail:
                    hash_at = tail.index("#")
                    inline_comment = "  " + tail[hash_at:].strip()
            out_lines.append(f"{key}={new_val}{inline_comment}")
            seen.add(key)
        else:
            out_lines.append(s)

    for k, v in values.items():
        if k not in seen:
            out_lines.append(f"{k}={v}")

    ENV_PATH.write_text("\n".join(out_lines) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# setup-keys
# ─────────────────────────────────────────────────────────────────────────────
@app.command("setup-keys")
def setup_keys(
    no_validate: bool = typer.Option(False, "--no-validate",
                                     help="Skip the validate-keys prompt at the end."),
) -> None:
    """Paste a block of API keys; writes them into .env with canonical names."""
    console.print("[bold]Paste your API keys.[/bold] End with a blank line.")
    console.print("Accepted formats per line: [cyan]NAME=value[/], [cyan]NAME: value[/], "
                  "[cyan]NAME value[/]. Lines starting with [cyan]#[/] are ignored.\n")

    buf: list[str] = []
    for line in sys.stdin:
        if line.strip() == "":
            if buf:
                break
            else:
                continue
        buf.append(line.rstrip("\n"))
    pasted = "\n".join(buf)
    if not pasted.strip():
        console.print("[yellow]No input received. Aborting.[/yellow]")
        raise typer.Exit(code=1)

    parsed, unknown = _parse_pasted_block(pasted)

    existing = _read_env()
    merged = {**existing, **parsed}
    if "SEC_USER_AGENT" not in merged or not merged.get("SEC_USER_AGENT"):
        merged["SEC_USER_AGENT"] = DEFAULT_SEC_USER_AGENT
    # Ensure runtime defaults
    merged.setdefault("LOG_LEVEL", "INFO")
    merged.setdefault("DATABASE_URL", "sqlite:///data/state.db")

    _write_env(merged)

    for u in unknown:
        console.print(f"[yellow]Unknown key: {u}; ignoring "
                      f"(add to FUZZY_MAP in src/cli.py if needed)[/yellow]")

    table = Table(title="Keys written to .env", show_lines=False)
    table.add_column("KEY")
    table.add_column("STATUS")
    canonical_names = sorted({v for v in FUZZY_MAP.values()} | {"SEC_USER_AGENT"})
    for k in canonical_names:
        v = merged.get(k, "")
        table.add_row(k, "[green]set[/green]" if v else "[dim]blank[/dim]")
    console.print(table)
    console.print(f"[green]Wrote {ENV_PATH}.[/green]")

    if not no_validate:
        if Confirm.ask("Validate keys now?", default=True):
            reload_config()
            validate_keys()


# ─────────────────────────────────────────────────────────────────────────────
# validate-keys
# ─────────────────────────────────────────────────────────────────────────────
def _validate_anthropic(key: str) -> tuple[str, str]:
    try:
        from anthropic import Anthropic
        c = Anthropic(api_key=key)
        c.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4,
            messages=[{"role": "user", "content": "ping"}],
        )
        return "WORKING", "auth ok"
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "auth" in msg or "permission" in msg or "invalid" in msg:
            return "INVALID", str(e)[:80]
        return "SET BUT UNVERIFIED", str(e)[:80]


def _validate_deepseek(key: str) -> tuple[str, str]:
    try:
        from openai import OpenAI
        c = OpenAI(api_key=key, base_url="https://api.deepseek.com")
        c.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
        )
        return "WORKING", "auth ok"
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "auth" in msg or "invalid" in msg:
            return "INVALID", str(e)[:80]
        return "SET BUT UNVERIFIED", str(e)[:80]


def _validate_gemini(key: str) -> tuple[str, str]:
    try:
        from google import genai
        from google.genai import types as genai_types
        c = genai.Client(api_key=key)
        c.models.generate_content(
            model="gemini-2.5-flash",
            contents="ping",
            config=genai_types.GenerateContentConfig(max_output_tokens=4),
        )
        return "WORKING", "auth ok"
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "403" in msg or "auth" in msg or "permission" in msg or "invalid" in msg:
            return "INVALID", str(e)[:80]
        return "SET BUT UNVERIFIED", str(e)[:80]


def _validate_openai(key: str) -> tuple[str, str]:
    try:
        from openai import OpenAI
        c = OpenAI(api_key=key)
        c.models.list()
        return "WORKING", "auth ok"
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "auth" in msg or "invalid" in msg:
            return "INVALID", str(e)[:80]
        return "SET BUT UNVERIFIED", str(e)[:80]


def _validate_http(name: str, url: str, *, params: dict | None = None,
                   headers: dict | None = None, ok_status: tuple[int, ...] = (200,)) -> tuple[str, str]:
    try:
        r = httpx.get(url, params=params, headers=headers, timeout=10.0)
        if r.status_code in ok_status:
            return "WORKING", f"{r.status_code} ok"
        if r.status_code in (401, 403):
            return "INVALID", f"{r.status_code} {r.reason_phrase}"
        return "SET BUT UNVERIFIED", f"{r.status_code} {r.reason_phrase}"
    except Exception as e:
        return "SET BUT UNVERIFIED", f"{name} probe error: {str(e)[:60]}"


# Map env-var name → validator function (key) -> (status, note)
DATA_VALIDATORS: dict[str, callable] = {
    "FINNHUB_API_KEY": lambda k: _validate_http(
        "finnhub", "https://finnhub.io/api/v1/quote",
        params={"symbol": "AAPL", "token": k}),
    # FMP: 200 with non-empty array = WORKING; 200 with {"Error Message": ...} = INVALID
    "FMP_API_KEY": lambda k: (lambda r: (
        ("WORKING", "200 ok") if r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) > 0 else
        ("INVALID", f"{r.status_code} {r.text[:80]}") if r.status_code in (401, 403) or
            (r.status_code == 200 and "Error Message" in r.text) else
        ("SET BUT UNVERIFIED", f"{r.status_code}")
    ))(httpx.get("https://financialmodelingprep.com/api/v3/profile/AAPL",
                 params={"apikey": k}, timeout=10.0)),
    "ALPHA_VANTAGE_API_KEY": lambda k: _validate_http(
        "alpha_vantage", "https://www.alphavantage.co/query",
        params={"function": "GLOBAL_QUOTE", "symbol": "AAPL", "apikey": k}),
    "FINANCIAL_DATASETS_API_KEY": lambda k: _validate_http(
        "financial_datasets", "https://api.financialdatasets.ai/financials/income-statements",
        params={"ticker": "AAPL", "limit": "1"},
        headers={"X-API-KEY": k}),
    "GUARDIAN_API_KEY": lambda k: _validate_http(
        "guardian", "https://content.guardianapis.com/search",
        params={"q": "ai", "page-size": "1", "api-key": k}),
    "MARKETAUX_API_KEY": lambda k: _validate_http(
        "marketaux", "https://api.marketaux.com/v1/news/all",
        params={"api_token": k, "limit": "1"}),
    "NEWSAPI_KEY": lambda k: _validate_http(
        "newsapi", "https://newsapi.org/v2/top-headlines",
        params={"country": "us", "pageSize": "1", "apiKey": k}),
    "NEWSDATA_API_KEY": lambda k: _validate_http(
        "newsdata", "https://newsdata.io/api/1/news",
        params={"apikey": k, "size": "1"}),
    "FRED_API_KEY": lambda k: _validate_http(
        "fred", "https://api.stlouisfed.org/fred/series",
        params={"series_id": "GNPCA", "api_key": k, "file_type": "json"}),
    "OPENFDA_API_KEY": lambda k: _validate_http(
        "openfda", "https://api.fda.gov/drug/event.json",
        params={"api_key": k, "limit": "1"}),
    "USPTO_API_KEY": lambda k: _validate_http(
        "uspto", "https://api.patentsview.org/patents/query",
        params={"q": '{"_eq":{"patent_id":"10000000"}}'}),
    "EIA_API_KEY": lambda k: _validate_http(
        "eia", "https://api.eia.gov/v2/",
        params={"api_key": k}),
    "SAM_GOV_API_KEY": lambda k: _validate_http(
        "sam_gov", "https://api.sam.gov/opportunities/v2/search",
        params={"limit": "1", "api_key": k},
        ok_status=(200, 400)),  # 400 means key accepted, query invalid
    "GITHUB_TOKEN": lambda k: _validate_http(
        "github", "https://api.github.com/user",
        headers={"Authorization": f"Bearer {k}", "Accept": "application/vnd.github+json"}),
    "TAVILY_API_KEY": lambda k: (lambda r: (
        "WORKING" if r.status_code == 200 else
        ("INVALID" if r.status_code in (401, 403) else "SET BUT UNVERIFIED"),
        f"{r.status_code}",
    ))(httpx.post("https://api.tavily.com/search",
                  json={"api_key": k, "query": "ping", "max_results": 1},
                  timeout=10.0)),
    # Firecrawl: requires POST /v1/scrape (not GET — GET returns 404); success=true in body
    "FIRECRAWL_API_KEY": lambda k: (lambda r: (
        ("WORKING", "200 ok") if r.status_code == 200 and r.json().get("success") is True else
        ("INVALID", f"{r.status_code} {r.text[:80]}") if r.status_code in (401, 403) else
        ("SET BUT UNVERIFIED", f"{r.status_code}")
    ))(httpx.post("https://api.firecrawl.dev/v1/scrape",
                  json={"url": "https://example.com", "formats": ["markdown"]},
                  headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
                  timeout=15.0)),
    "EXA_API_KEY": lambda k: _validate_http(
        "exa", "https://api.exa.ai/search",
        headers={"x-api-key": k},
        ok_status=(200, 400, 405)),
    "SERPER_API_KEY": lambda k: _validate_http(
        "serper", "https://google.serper.dev/search",
        headers={"X-API-KEY": k},
        ok_status=(200, 400, 405)),
    "SEMANTIC_SCHOLAR_API_KEY": lambda k: _validate_http(
        "s2", "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": "ai", "limit": "1"},
        headers={"x-api-key": k}),
    "CORE_API_KEY": lambda k: _validate_http(
        "core", "https://api.core.ac.uk/v3/search/works",
        params={"q": "ai", "limit": "1"},
        headers={"Authorization": f"Bearer {k}"}),
    "NCBI_API_KEY": lambda k: _validate_http(
        "ncbi", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi",
        params={"api_key": k, "db": "pubmed"}),
    "STOCKTWITS_API_KEY": lambda k: _validate_http(
        "stocktwits", "https://api.stocktwits.com/api/2/streams/symbol/AAPL.json",
        params={"access_token": k}),
}

LLM_VALIDATORS: dict[str, callable] = {
    "ANTHROPIC_API_KEY": _validate_anthropic,
    "DEEPSEEK_API_KEY": _validate_deepseek,
    "GEMINI_API_KEY": _validate_gemini,
    "OPENAI_API_KEY": _validate_openai,
}

ALL_KEYS = list(LLM_VALIDATORS.keys()) + list(DATA_VALIDATORS.keys()) + ["SEC_USER_AGENT"]


def _audit(line: str) -> None:
    audit_path = ROOT / "data" / ".config_audit.log"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with audit_path.open("a") as f:
        f.write(f"{ts} {line}\n")


def _rewire_llm_routing(working_providers: set[str]) -> list[str]:
    """Rewrites config.yaml llm_routing so only working providers are referenced.

    Strategy:
      - For each role, if its primary provider isn't working, swap it for the first
        working provider in priority order [anthropic, deepseek, gemini, openai].
      - If its fallback provider isn't working, do the same.
      - If only one provider works, it becomes both primary and fallback (with audit warning).
      - If no providers work, leave config alone and warn.

    Returns list of human-readable change descriptions.
    """
    raw = yaml.safe_load(CONFIG_YAML_PATH.read_text())
    routing = raw.get("llm_routing", {})

    priority = ["anthropic", "deepseek", "gemini", "openai"]
    canonical_models = {
        "anthropic": ("claude-haiku-4-5", "claude-haiku-4-5"),
        "deepseek": ("deepseek-chat", "deepseek-reasoner"),
        "gemini": ("gemini-2.5-flash", "gemini-2.5-pro"),
        "openai": ("gpt-4o-mini", "gpt-4o"),
    }
    available = [p for p in priority if p in working_providers]
    if not available:
        _audit("validate-keys: NO LLM PROVIDERS WORKING — config.yaml left unchanged")
        return ["WARNING: no working LLM providers; config.yaml unchanged"]

    changes: list[str] = []
    for role_name, role_cfg in routing.items():
        primary = role_cfg.get("provider")
        fallback = role_cfg.get("fallback_provider")
        new_primary = primary
        new_fallback = fallback

        if primary not in working_providers:
            new_primary = available[0]
            cheap, _ = canonical_models[new_primary]
            role_cfg["provider"] = new_primary
            role_cfg["model"] = cheap
            changes.append(f"role={role_name} primary {primary} -> {new_primary}")

        # ensure fallback is a different working provider when possible
        if fallback not in working_providers:
            alt = next((p for p in available if p != new_primary), new_primary)
            cheap, _ = canonical_models[alt]
            role_cfg["fallback_provider"] = alt
            role_cfg["fallback_model"] = cheap
            new_fallback = alt
            changes.append(f"role={role_name} fallback {fallback} -> {alt}")

        if new_primary == new_fallback and len(available) == 1:
            changes.append(f"role={role_name}: single-provider mode ({new_primary})")

    if changes:
        CONFIG_YAML_PATH.write_text(yaml.safe_dump(raw, sort_keys=False))
        for c in changes:
            _audit(f"validate-keys: {c}")
    else:
        _audit("validate-keys: no llm_routing changes needed")
    return changes


@app.command("validate-keys")
def validate_keys() -> None:
    """Test every key with a minimal-cost call; rewire llm_routing fallbacks."""
    cfg = reload_config()
    statuses: dict[str, dict[str, str]] = {}

    table = Table(title="Key validation results")
    table.add_column("KEY")
    table.add_column("STATUS")
    table.add_column("NOTES")

    working_providers: set[str] = set()

    # LLM keys
    provider_for_envvar = {
        "ANTHROPIC_API_KEY": "anthropic",
        "DEEPSEEK_API_KEY": "deepseek",
        "GEMINI_API_KEY": "gemini",
        "OPENAI_API_KEY": "openai",
    }
    for key in LLM_VALIDATORS:
        val = getattr(cfg.secrets, key, "") or ""
        if not val:
            statuses[key] = {"status": "NOT SET", "notes": ""}
            table.add_row(key, "[dim]NOT SET[/dim]", "")
            continue
        status, note = LLM_VALIDATORS[key](val)
        statuses[key] = {"status": status, "notes": note}
        colour = {"WORKING": "green", "INVALID": "red",
                  "SET BUT UNVERIFIED": "yellow", "NOT SET": "dim"}[status]
        table.add_row(key, f"[{colour}]{status}[/{colour}]", note)
        if status == "WORKING":
            working_providers.add(provider_for_envvar[key])

    # Data API keys
    for key, validator in DATA_VALIDATORS.items():
        val = getattr(cfg.secrets, key, "") or ""
        if not val:
            statuses[key] = {"status": "NOT SET", "notes": ""}
            table.add_row(key, "[dim]NOT SET[/dim]", "")
            continue
        try:
            status, note = validator(val)
        except Exception as e:
            status, note = "SET BUT UNVERIFIED", f"probe failed: {str(e)[:60]}"
        statuses[key] = {"status": status, "notes": note}
        colour = {"WORKING": "green", "INVALID": "red",
                  "SET BUT UNVERIFIED": "yellow", "NOT SET": "dim"}[status]
        table.add_row(key, f"[{colour}]{status}[/{colour}]", note)

    # SEC_USER_AGENT — always configured, no key
    sua = cfg.secrets.SEC_USER_AGENT
    if sua:
        statuses["SEC_USER_AGENT"] = {"status": "SET BUT UNVERIFIED", "notes": "no test endpoint"}
        table.add_row("SEC_USER_AGENT", "[yellow]configured[/yellow]", sua)
    else:
        statuses["SEC_USER_AGENT"] = {"status": "NOT SET", "notes": ""}
        table.add_row("SEC_USER_AGENT", "[dim]NOT SET[/dim]", "")

    console.print(table)

    # Persist statuses
    status_path = ROOT / "data" / ".key_status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps({
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "statuses": statuses,
    }, indent=2))

    # Rewire llm_routing
    changes = _rewire_llm_routing(working_providers)
    if changes:
        console.print("[bold]config.yaml llm_routing changes:[/bold]")
        for c in changes:
            console.print(f"  • {c}")
        reload_config()

    # Summary
    counts = {"WORKING": 0, "SET BUT UNVERIFIED": 0, "INVALID": 0, "NOT SET": 0}
    for v in statuses.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    console.print(
        f"[bold]{counts['WORKING']}[/bold] working, "
        f"[bold]{counts['SET BUT UNVERIFIED']}[/bold] unverified, "
        f"[bold]{counts['INVALID']}[/bold] invalid, "
        f"[bold]{counts['NOT SET']}[/bold] not set. "
        "Fallbacks configured. Run [cyan]visionairy2 ping[/cyan] to confirm "
        "LLM client routing works end-to-end."
    )


# ─────────────────────────────────────────────────────────────────────────────
# init / ping / discover / analyse-doc
# ─────────────────────────────────────────────────────────────────────────────
@app.command("init")
def init_cmd() -> None:
    """Initialise database and seed watchlist."""
    from src.storage.db import init_db
    from scripts.seed_watchlist import seed
    init_db()
    n = seed()
    console.print(f"[green]db initialised; {n} watchlist rows present.[/green]")


@app.command("ping")
def ping_cmd() -> None:
    """Exercise every llm_routing role; report which routes succeed."""
    from src.llm.client import complete
    cfg = reload_config()
    table = Table(title="LLM routing ping")
    table.add_column("ROLE")
    table.add_column("PROVIDER")
    table.add_column("MODEL")
    table.add_column("STATUS")
    for role_name, routing in cfg.llm_routing.items():
        try:
            text = complete(
                role=role_name,
                system="Respond with the single word 'pong'.",
                user="ping",
                max_tokens=8,
                agent_name=f"ping_{role_name}",
            )
            ok = bool(text)
            table.add_row(role_name, routing.provider, routing.model,
                          "[green]ok[/green]" if ok else "[red]empty[/red]")
        except Exception as e:
            table.add_row(role_name, routing.provider, routing.model,
                          f"[red]failed: {str(e)[:50]}[/red]")
    console.print(table)


@app.command("discover")
def discover_cmd() -> None:
    """Mode 1 — discovery scan. Implemented in Session 3."""
    console.print("[yellow]Mode 1 not yet implemented (Session 3).[/yellow]")


@app.command("analyse-doc")
def analyse_doc_cmd(url: str = typer.Argument(...)) -> None:
    """Mode 3 — analyse a document by URL. Implemented in Session 3."""
    _ = url
    console.print("[yellow]Mode 3 not yet implemented (Session 3).[/yellow]")


# ─────────────────────────────────────────────────────────────────────────────
# sources subcommand group
# ─────────────────────────────────────────────────────────────────────────────
sources_app = typer.Typer(no_args_is_help=True, help="Source client management.")
app.add_typer(sources_app, name="sources")


@sources_app.command("list")
def sources_list_cmd() -> None:
    """List all source clients with their availability status."""
    from src.sources.registry import list_available_sources, list_disabled_sources, SOURCE_REGISTRY, _register_all
    cfg = get_config()
    if not SOURCE_REGISTRY:
        _register_all()
    available = set(list_available_sources(cfg))
    disabled = dict(list_disabled_sources(cfg))

    table = Table(title=f"Source Clients ({len(SOURCE_REGISTRY)} total)")
    table.add_column("SOURCE ID")
    table.add_column("NEEDS KEY")
    table.add_column("SECTOR ROUTED")
    table.add_column("FALLBACK")
    table.add_column("STATUS")

    for sid in sorted(SOURCE_REGISTRY.keys()):
        cls = SOURCE_REGISTRY[sid]
        status = "[green]available[/green]" if sid in available else f"[red]disabled: {disabled.get(sid,'unknown')}[/red]"
        needs_key = "[dim]no[/dim]" if not cls.needs_key else f"[cyan]{cls.key_env_var}[/cyan]"
        sector = "[yellow]yes[/yellow]" if cls.sector_routed else "[dim]no[/dim]"
        fallback = "[dim]yes[/dim]" if cls.is_fallback else "[dim]no[/dim]"
        table.add_row(sid, needs_key, sector, fallback, status)
    console.print(table)
    console.print(f"[bold]{len(available)}[/bold] available, [bold]{len(disabled)}[/bold] disabled.")


# ─────────────────────────────────────────────────────────────────────────────
# fetch command
# ─────────────────────────────────────────────────────────────────────────────
@app.command("fetch")
def fetch_cmd(
    source: Optional[str] = typer.Option(None, "--source", help="Source ID to fetch from."),
    ticker: Optional[str] = typer.Option(None, "--ticker", help="Ticker symbol."),
    query_string: Optional[str] = typer.Option(None, "--query-string", help="Search query or URL."),
    sector: Optional[str] = typer.Option(None, "--sector", help="Sector ID for sector routing."),
    all_sources: bool = typer.Option(False, "--all", help="Fetch from all available sources."),
    lookback: int = typer.Option(7, "--lookback", help="Lookback days."),
) -> None:
    """Fetch documents from one or all source clients."""
    from src.sources.base import SourceQuery
    from src.sources.registry import get_client, list_available_sources
    from src.ingestion.fetcher import ParallelFetcher

    cfg = get_config()
    query = SourceQuery(
        ticker=ticker,
        query_string=query_string or ticker,
        lookback_days=lookback,
        limit=25,
        sector_id=sector,
    )

    if all_sources and ticker:
        if not sector:
            console.print("[yellow]--sector recommended with --all for proper sector routing.[/yellow]")
        fetcher = ParallelFetcher(cfg)
        results = fetcher.fetch_for_ticker(
            ticker=ticker,
            sector_id=sector or "ai_chips_compute",
            lookback_days_quant=lookback,
            lookback_days_qual=lookback * 2,
        )
    elif source:
        try:
            client = get_client(source, cfg)
            if not client.is_available():
                console.print(f"[red]Source '{source}' is not available (key not set).[/red]")
                raise typer.Exit(code=1)
            results = [client.fetch(query)]
        except KeyError:
            console.print(f"[red]Unknown source: {source!r}[/red]")
            raise typer.Exit(code=1)
    else:
        console.print("[red]Provide --source <id> or --all --ticker <symbol>.[/red]")
        raise typer.Exit(code=1)

    total_docs = 0
    table = Table(title="Fetch Results")
    table.add_column("SOURCE")
    table.add_column("DOCS")
    table.add_column("ERRORS")
    for r in results:
        total_docs += len(r.documents)
        err_str = "; ".join(r.errors[:2]) if r.errors else ""
        table.add_row(
            r.source,
            str(len(r.documents)),
            f"[red]{err_str[:80]}[/red]" if err_str else "[green]ok[/green]",
        )
    console.print(table)
    console.print(f"[bold]Total documents:[/bold] {total_docs}")


# ─────────────────────────────────────────────────────────────────────────────
# extract / resolve / score commands
# ─────────────────────────────────────────────────────────────────────────────
@app.command("extract")
def extract_cmd(
    doc_id: str = typer.Option(..., "--doc-id", help="Document source_id to extract entities from."),
) -> None:
    """Run entity extraction on a stored document."""
    from src.llm.client import complete
    from src.ingestion.extractor import EntityExtractor
    from src.storage.db import get_session_factory
    from src.storage.models import Document

    cfg = get_config()
    session_factory = get_session_factory()
    with session_factory() as session:
        doc = session.query(Document).filter_by(source_id=doc_id).first()
        if not doc:
            console.print(f"[red]Document not found: {doc_id}[/red]")
            raise typer.Exit(code=1)
        text = doc.title or ""

    extractor = EntityExtractor(
        type("LLM", (), {"complete": staticmethod(complete)})()
    )
    entities = extractor.extract_companies(text)
    console.print(f"Entities from document [cyan]{doc_id}[/cyan]:")
    for e in entities:
        console.print(f"  {e.get('name','')} [{e.get('ticker_guess','?')}] — {e.get('context','')}")


@app.command("resolve")
def resolve_cmd(
    name: str = typer.Option(..., "--name", help="Company name to resolve to ticker."),
) -> None:
    """Resolve a company name to a ticker symbol."""
    from src.llm.client import complete
    from src.ingestion.ticker_resolver import TickerResolver
    from src.storage.db import get_session_factory

    cfg = get_config()
    session_factory = get_session_factory()
    resolver = TickerResolver(
        db_session_factory=session_factory,
        llm_client=type("LLM", (), {"complete": staticmethod(complete)})(),
    )
    ticker = resolver.resolve(name)
    if ticker:
        console.print(f"[green]{name}[/green] -> [bold]{ticker}[/bold]")
    else:
        console.print(f"[yellow]Could not resolve ticker for: {name}[/yellow]")


@app.command("score")
def score_cmd(
    ticker: str = typer.Argument(..., help="Ticker symbol to score."),
) -> None:
    """Compute interestingness score for a ticker using cached data."""
    from src.ingestion.scorer import InterestingnessScorer
    from src.storage.db import get_session_factory
    from src.storage.models import Company, Document, Mention

    cfg = get_config()
    session_factory = get_session_factory()
    scorer = InterestingnessScorer()

    with session_factory() as session:
        company = session.query(Company).filter_by(ticker=ticker.upper()).first()
        if not company:
            console.print(f"[red]Company not found in DB: {ticker}[/red]")
            raise typer.Exit(code=1)

        mentions = session.query(Mention).filter_by(company_id=company.id).all()
        doc_links = []
        for m in mentions:
            doc = session.query(Document).filter_by(id=m.document_id).first()
            if doc:
                from src.sources.base import SourceDocument
                from datetime import timezone
                sd = SourceDocument(
                    source=doc.source,
                    source_id=doc.source_id,
                    url=doc.url or "",
                    content_hash=doc.content_hash,
                    doc_type=doc.doc_type,
                    title=doc.title or "",
                    published_at=doc.published_at,
                    fetched_at=doc.fetched_at,
                    raw_payload={},
                )
                doc_links.append((sd, m.weight))

    if not doc_links:
        console.print(f"[yellow]No documents found for {ticker}. Run 'fetch --all --ticker {ticker}' first.[/yellow]")
        raise typer.Exit(code=0)

    result = scorer.score_company(company.id, doc_links, cfg)
    console.print(f"\n[bold]Interestingness score for {ticker}:[/bold] {result['score']}")
    table = Table(title="Score Factors")
    table.add_column("FACTOR")
    table.add_column("VALUE")
    for k, v in result["factors"].items():
        table.add_row(k, str(v))
    console.print(table)


if __name__ == "__main__":
    app()
