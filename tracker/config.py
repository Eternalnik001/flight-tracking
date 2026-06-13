"""All knobs live here. Secrets come from environment variables (GitHub Actions secrets)."""
from __future__ import annotations

import calendar
import os
from datetime import date
from pathlib import Path


def _load_dotenv() -> None:
    """Load a local .env (project root) into os.environ for local runs.

    Real environment variables (e.g. GitHub Actions secrets) always win — we
    only fill in keys that aren't already set.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

# ---------------------------------------------------------------------------
# Trip definition
# ---------------------------------------------------------------------------
ORIGIN = "BLR"  # Bangalore – Kempegowda International

# Up to ~20 destinations as IATA *city* codes.
# Trunk routes (DEL/BOM/HYD/MAA) have the deepest, freshest cache on Travelpayouts.
# Long-tail routes may return little or stale data – that is expected, not a bug.
DESTINATIONS = ["DEL", "BOM", "HYD", "MAA", "CCU", "GOI", "PNQ", "AMD", "COK", "JAI"]

TRIP_YEAR = int(os.getenv("TRIP_YEAR", "2026"))
# Months to track, as a comma-separated list (e.g. "8,11" = August + November).
# Each is scanned independently; the frontend shows one window per month.
TRIP_MONTHS = [int(m) for m in os.getenv("TRIP_MONTHS", "8,11").split(",") if m.strip()]
NIGHTS = 3             # 3 nights / 4 days  ->  depart day D, return day D+3

CURRENCY = "inr"       # Travelpayouts wants lowercase; SerpApi gets CURRENCY.upper()

# ---------------------------------------------------------------------------
# Hybrid gating: when is it worth spending a (rate-limited) live SerpApi call?
# ---------------------------------------------------------------------------
DROP_PCT_TRIGGER = 0.10        # confirm live if the cached cheapest dropped >= 10% vs last run
ABS_TARGET: dict[str, float] = {  # OR if cached cheapest falls at/below an absolute INR target
    # "DEL": 5000,
    # "BOM": 4500,
}
MAX_LIVE_CALLS = int(os.getenv("MAX_LIVE_CALLS", "8"))  # hard cap per run -> stays inside SerpApi free tier
# Live backfill: routes/months the free cache leaves empty get one real live price.
# Refreshed only when older than this many days, so we don't re-spend the budget daily.
LIVE_STALE_DAYS = int(os.getenv("LIVE_STALE_DAYS", "3"))

# ---------------------------------------------------------------------------
# Concurrency / politeness for the cached scan
# ---------------------------------------------------------------------------
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "6"))
REQUEST_TIMEOUT = 30  # seconds

# ---------------------------------------------------------------------------
# History retention: the append-only log grows with every run. Keep a rolling
# window so the table (and future trend queries) stay small. 0 disables pruning.
# ---------------------------------------------------------------------------
HISTORY_RETENTION_DAYS = int(os.getenv("HISTORY_RETENTION_DAYS", "180"))

# ---------------------------------------------------------------------------
# Secrets (set as GitHub Actions secrets / local env vars)
# ---------------------------------------------------------------------------
TRAVELPAYOUTS_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

# For GitHub Actions you MUST point this at a real Postgres (Neon/Supabase free tier),
# because the runner's filesystem is wiped each run, so SQLite would forget yesterday's
# prices and change-detection would never fire. SQLite is only for local testing.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///flights.db")


def trip_combos(month: int) -> list[tuple[date, date]]:
    """Every (depart, return) pair for an N-night stay inside `month`.

    For a 30-day November with NIGHTS=3 this yields 27 combos:
    depart Nov 1 / return Nov 4  ...  depart Nov 27 / return Nov 30.
    """
    last_day = calendar.monthrange(TRIP_YEAR, month)[1]
    combos: list[tuple[date, date]] = []
    day = 1
    while day + NIGHTS <= last_day:
        depart = date(TRIP_YEAR, month, day)
        ret = date(TRIP_YEAR, month, day + NIGHTS)
        combos.append((depart, ret))
        day += 1
    return combos


def trip_month_str(month: int) -> str:
    """YYYY-MM string the calendar endpoint expects."""
    return f"{TRIP_YEAR}-{month:02d}"


def sample_combo(month: int) -> tuple[date, date]:
    """A representative mid-month (depart, return) for a single live price probe."""
    combos = trip_combos(month)
    return combos[len(combos) // 2]
