"""Two clients:

  Travelpayouts (Aviasales Data API)  -> CACHED prices, free, used for the broad month scan.
  SerpApi Google Flights             -> LIVE prices, gated, used only to confirm candidates.
"""
from __future__ import annotations

import httpx

# ---------------------------------------------------------------------------
# Travelpayouts – cached "price calendar" (one call returns a whole month)
# ---------------------------------------------------------------------------
# NOTE: Travelpayouts has reshuffled endpoints over the years. If you get empty
# `data`, the two most likely fixes are (a) try depart_date as "YYYY-MM-01"
# instead of "YYYY-MM", and (b) confirm this path against the current docs:
#   https://travelpayouts-data-api.readthedocs.io/  ->  /v1/prices/calendar
TP_CALENDAR_URL = "https://api.travelpayouts.com/v1/prices/calendar"


class Travelpayouts:
    def __init__(self, token: str, currency: str, timeout: int = 30) -> None:
        self.token = token
        self.currency = currency
        self.timeout = timeout

    async def calendar(
        self,
        client: httpx.AsyncClient,
        origin: str,
        destination: str,
        month: str,            # "YYYY-MM"
        length: int | None = None,  # stay length in days -> round-trip prices; omit for one-way
    ) -> dict[str, float]:
        """Return {date_str: cheapest_price} for each day of `month`.

        - length=None  -> ONE-WAY cheapest per departure day.
        - length=N     -> ROUND-TRIP cheapest per departure day with an N-day stay.
        """
        params = {
            "origin": origin,
            "destination": destination,
            "depart_date": month,           # YYYY-MM (see note above if empty)
            "calendar_type": "departure_date",
            "currency": self.currency,
            "token": self.token,
        }
        if length is not None:
            params["length"] = length

        resp = await client.get(TP_CALENDAR_URL, params=params, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()

        out: dict[str, float] = {}
        for day, info in (payload.get("data") or {}).items():
            price = info.get("price") if isinstance(info, dict) else None
            if price is not None:
                out[day] = float(price)
        return out


# ---------------------------------------------------------------------------
# SerpApi Google Flights – live, accurate (covers IndiGo/Air India/Akasa/SpiceJet)
# ---------------------------------------------------------------------------
SERPAPI_URL = "https://serpapi.com/search"


class SerpApi:
    def __init__(self, api_key: str, currency: str = "INR") -> None:
        self.api_key = api_key
        self.currency = currency

    def price(
        self,
        departure_id: str,
        arrival_id: str,
        outbound_date: str,        # "YYYY-MM-DD"
        return_date: str | None = None,  # set for round-trip
        timeout: int = 60,
    ) -> dict:
        """One live lookup. Returns the cheapest price plus Google's price-insights.

        For a round trip the first response already carries the total round-trip
        price, so a single call is enough for tracking (no departure_token needed).
        """
        params = {
            "engine": "google_flights",
            "departure_id": departure_id,
            "arrival_id": arrival_id,
            "outbound_date": outbound_date,
            "currency": self.currency,
            "hl": "en",
            "gl": "in",
            "api_key": self.api_key,
        }
        if return_date:
            params["type"] = 1            # round trip
            params["return_date"] = return_date
        else:
            params["type"] = 2            # one way

        resp = httpx.get(SERPAPI_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        prices: list[float] = []
        for key in ("best_flights", "other_flights"):
            for flight in data.get(key, []) or []:
                if flight.get("price") is not None:
                    prices.append(float(flight["price"]))

        insights = data.get("price_insights") or {}
        return {
            "price": min(prices) if prices else None,
            "price_level": insights.get("price_level"),          # low / typical / high
            "typical_range": insights.get("typical_price_range"),  # [low, high]
        }
