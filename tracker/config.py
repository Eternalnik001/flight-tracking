"""All knobs live here. Secrets come from environment variables (GitHub Actions secrets)."""
from __future__ import annotations

import calendar
import os
from datetime import date

# ---------------------------------------------------------------------------
# Trip definition
# ---------------------------------------------------------------------------
ORIGIN = "BLR"  # Bangalore – Kempegowda International

# Up to ~20 destinations as IATA *city* codes.
# Trunk routes (DEL/BOM/HYD/MAA) have the deepest, freshest cache on Travelpayouts.
# Long-tail routes may return little or stale data – that is expected, not a bug.
DESTINATIONS = ["DEL", "BOM", "HYD", "MAA", "CCU", "GOI", "PNQ", "AMD", "COK", "JAI"]

TRIP_YEAR = int(os.getenv("TRIP_YEAR", "2026"))
TRIP_MONTH = 11        # November
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

# ---------------------------------------------------------------------------
# Concurrency / politeness for the cached scan
# ---------------------------------------------------------------------------
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "6"))
REQUEST_TIMEOUT = 30  # seconds

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
EMAIL_TO = [e.strip() for e in os.getenv("EMAIL_TO", "").split(",") if e.strip()]
EMAIL_FROM = os.getenv("EMAIL_FROM", "Flight Tracker <onboarding@resend.dev>")
EMAIL_SUBJECT_PREFIX = "BLR flight matrix"

# ---------------------------------------------------------------------------
# Secrets (set as GitHub Actions secrets / local env vars)
# ---------------------------------------------------------------------------
TRAVELPAYOUTS_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")

# For GitHub Actions you MUST point this at a real Postgres (Neon/Supabase free tier),
# because the runner's filesystem is wiped each run, so SQLite would forget yesterday's
# prices and change-detection would never fire. SQLite is only for local testing.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///flights.db")


def trip_combos() -> list[tuple[date, date]]:
    """Every (depart, return) pair for an N-night stay inside the trip month.

    For a 30-day November with NIGHTS=3 this yields 27 combos:
    depart Nov 1 / return Nov 4  ...  depart Nov 27 / return Nov 30.
    """
    last_day = calendar.monthrange(TRIP_YEAR, TRIP_MONTH)[1]
    combos: list[tuple[date, date]] = []
    day = 1
    while day + NIGHTS <= last_day:
        depart = date(TRIP_YEAR, TRIP_MONTH, day)
        ret = date(TRIP_YEAR, TRIP_MONTH, day + NIGHTS)
        combos.append((depart, ret))
        day += 1
    return combos


def trip_month_str() -> str:
    """YYYY-MM string the calendar endpoint expects."""
    return f"{TRIP_YEAR}-{TRIP_MONTH:02d}"
