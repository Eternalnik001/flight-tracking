# ✈️ FlightTracker — Bengaluru → domestic India

**A zero-cost, fully-automated fare tracker for one-way + round-trip flights out of Bengaluru (BLR).**
Pick destinations, and every morning it scans the cheapest 3-night / 4-day round trips across a whole
month, stores the history, flags real price drops, and surfaces it all on a live dashboard + email.

🔗 **Live:** https://eternalnik001.github.io/flight-tracking/
💸 **Running cost:** ₹0 (entirely on free tiers)
⏱️ **Built end-to-end in under 5 hours** — vibe-coded with Claude Code.

---

## TL;DR

| | |
|---|---|
| **Who it's for** | Anyone planning domestic travel from Bengaluru who wants to book at the right price without manually checking 10 routes × 27 dates every day. |
| **What it does** | Tracks **August + November 2026** fares for a watchlist of destinations, daily, and shows the cheapest option per route. |
| **The insight** | A free cached API does the broad month-wide scan; a metered live API is spent *only* on confirmed price drops. Cost stays flat whether you track 5 routes or 200. |
| **Stack** | Python · Travelpayouts · SerpApi · Supabase Postgres · Resend · GitHub Actions · static GitHub Pages frontend. |
| **Status** | Shipped & live. Daily cron green, dashboard live, email delivering. |

---

## Why it's free (the hybrid model)

Live flight APIs are expensive and rate-limited; naively checking 10 routes × ~27 date combos × 2 months
daily would blow any free tier in hours. The trick is a **two-tier scan**:

1. **Broad scan — free & cached.** One [Travelpayouts](https://travelpayouts.com) `month-matrix` call per
   route per leg returns a whole month of cheapest one-way fares. Round trips are assembled as "split"
   fares (outbound + return leg). All routes run concurrently — a full scan takes seconds.
2. **Diff.** Each run is compared against the previous snapshot in Postgres.
3. **Live confirmation — gated.** Only date/route combos whose cached price **dropped ≥ `DROP_PCT_TRIGGER`**
   (or fell below an absolute target) are confirmed live against **SerpApi Google Flights**, hard-capped at
   `MAX_LIVE_CALLS` per run to stay inside the free tier.
4. **Surface it.** Prices land in Supabase → the live dashboard reads them and an HTML matrix is emailed via
   Resend.

> **Net effect:** broad coverage at the cost of a few targeted live calls per day. Adding routes or months
> costs nothing extra on the scan side.

---

## Architecture

```
            ┌──────────────────────────────────────────────────────────┐
            │  GitHub Actions  ·  cron 0 1 * * * UTC (06:30 IST, daily)  │
            │                                                            │
  Travelpayouts ──cached month scan──▶  tracker/  ──gated drops──▶  SerpApi
  (free, broad)                          │   │                      (live, capped)
                                         │   └──────────┐
                                         ▼              ▼
                                  Supabase Postgres   Resend email
                                  (latest + history + watchlist)
                                         ▲   │
   GitHub Pages frontend  ◀──reads──────┘   │
   (Apple-style dashboard) ──edits watchlist─┘
```

| Layer | Choice | Why |
|---|---|---|
| Cached fares | Travelpayouts `/v2/prices/month-matrix` | Whole month per call, free |
| Live fares | SerpApi Google Flights | Best Indian-LCC coverage (IndiGo/Air India/Akasa/SpiceJet) |
| State | Supabase Postgres | Survives between stateless CI runs; RLS lets the frontend read directly |
| Email | Resend | Generous free tier, simple API |
| Compute | GitHub Actions | Free scheduled cron, no server to run |
| Frontend | Static HTML/JS on GitHub Pages | Zero build, zero hosting cost |

---

## The frontend

A static, dependency-light page ([`web/`](web/)) with an Apple-inspired UI: frosted nav, gradient hero
with live stats, an Apple-style segmented control to switch **August / November**, animated destination
cards with a "Best deal" badge, automatic **dark mode**, and a personalised greeting via `?name=` links.

- **Reads** prices straight from Supabase with the public **anon key** (safe to expose — it's gated by the
  row-level-security policies in [`web/supabase_setup.sql`](web/supabase_setup.sql)).
- **Writes** the watchlist: pick routes in the UI → saved to Supabase → the next daily scan uses them.
- Honest empty states: a far-future month with no cached data says so rather than looking broken.

---

## Deploy your own

1. **Fork / clone** this repo.
2. **Create free accounts** and grab keys:
   - **Travelpayouts** → Aviasales program → API token
   - **SerpApi** → API key (~250 free searches/month)
   - **Resend** → API key (`onboarding@resend.dev` works until you verify a domain)
   - **Supabase** → new project → connection string + anon key
3. **Add repo secrets** — *Settings → Secrets and variables → Actions*:

   | Secret | Notes |
   |---|---|
   | `TRAVELPAYOUTS_TOKEN` | cached scan |
   | `SERPAPI_KEY` | live confirmation |
   | `DATABASE_URL` | **use the Supabase Session-pooler string** (IPv4) — the direct host is IPv6-only and times out on CI |
   | `RESEND_API_KEY` | email |
   | `EMAIL_FROM` / `EMAIL_TO` | sender needs a verified domain to reach arbitrary recipients |
   | `TRIP_YEAR` / `TRIP_MONTHS` | optional; default `2026` and `8,11` |
4. **Wire the frontend:** run [`web/supabase_setup.sql`](web/supabase_setup.sql) once in the Supabase SQL
   Editor, paste your Project URL + anon key into [`web/config.js`](web/config.js), and set
   *Settings → Pages → Source = GitHub Actions*.
5. **Done.** The daily cron in [`.github/workflows/track.yml`](.github/workflows/track.yml) runs it (or trigger
   manually from the Actions tab); [`pages.yml`](.github/workflows/pages.yml) deploys the frontend on push.

> **Postgres, not SQLite, on CI.** The runner's disk is wiped each run, so SQLite would forget yesterday's
> prices and change-detection would never fire. SQLite remains the local-testing default.

---

## Configure

Everything lives in [`tracker/config.py`](tracker/config.py):

| Knob | Default | Meaning |
|---|---|---|
| `TRIP_MONTHS` | `8, 11` | Months to track (env `TRIP_MONTHS="8,11,12"`). Each gets its own dashboard window. |
| `NIGHTS` | `3` | Stay length → depart D, return D+3 |
| `DROP_PCT_TRIGGER` | `0.10` | Confirm live if cached cheapest drops ≥ 10% vs last run |
| `ABS_TARGET` | `{}` | Optional per-route absolute INR target |
| `MAX_LIVE_CALLS` | `8` | Hard cap on live calls per run (protects free tier) |

**Destinations** are seeded from `DESTINATIONS` on first run, then live in the `watchlist` table — edit them
from the dashboard, not the code. The airport picker covers **53 airports across 29 states/UTs**.

---

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in your keys (.env is gitignored)
python -m tracker.main # writes report.html, updates the DB, emails if configured
```

`.env` is auto-loaded; real environment variables (CI secrets) always take precedence.

---

## Security

- **No secret leaks in logs.** [`tracker/security.py`](tracker/security.py) redacts API tokens, keys, and DB
  passwords from all error output (the Travelpayouts token rides in a URL query string, so this matters).
- **Fail-fast** on missing required secrets — without ever printing the value.
- **Pre-commit secret scanner** ([`scripts/check_secrets.py`](scripts/check_secrets.py) +
  [`.githooks/pre-commit`](.githooks/pre-commit)) blocks committing a `.env`, real keys, or a Supabase
  *service_role* key in the frontend. Enable with `git config core.hooksPath .githooks`.

---

## Known limits (deliberate scope)

- **Far-future months are empty until ~2–3 months out.** The Aviasales cache is populated by real user
  searches, so November shows little this far ahead — by design, not a bug. August already has data.
- **Single shared watchlist, no login.** Fine for a personal tool; the anon key can edit the watchlist.
  Add Supabase Auth if it goes multi-user.
- **Email to third parties needs a verified domain.** `onboarding@resend.dev` only sends to your own address.
- **Cron is best-effort.** GitHub may delay scheduled runs under load.

## Roadmap

- Per-card price-history sparkline (the `history` table already logs every run)
- "Biggest drops this week" section
- Additional months / one-off date ranges
- Optional accounts for multi-user watchlists

---

*Vibe-coded end-to-end in a single sub-5-hour session with Claude Code — from a flat folder of scripts to a
live, automated, secured product.*
