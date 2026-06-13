# BLR domestic flight price tracker

Monitors one-way + round-trip fares for **Bangalore → up to 20 domestic destinations**
across every 3-night/4-day date combination in November, picks the cheapest booking
strategy per date, and emails an HTML matrix. Runs free on **GitHub Actions** (Python).

## How it works (hybrid model)

1. **Broad scan — free, cached.** One Travelpayouts "price calendar" call per route per
   leg returns a whole month at once (outbound one-way, return one-way, and round-trip with
   a 3-night stay). All routes run concurrently, so a full scan takes seconds.
2. **Diff.** Each run is compared against the previous run stored in the database.
3. **Live confirmation — gated.** Only date/route combos whose cached price **dropped past
   your threshold** (or fell below an absolute target) are confirmed live against
   **SerpApi Google Flights**, capped at `MAX_LIVE_CALLS` per run so it stays inside the
   free tier. Cost stays flat whether you track 5 routes or 200.
4. **Email.** A summary table (cheapest option + change per route) plus a full per-route
   matrix, sent via Resend.

## Setup

1. Push these files to a new GitHub repo.
2. Create accounts and grab keys:
   - **Travelpayouts** (cached data, free): sign up → Aviasales program → API token.
   - **SerpApi** (live, ~100–250 free searches/month): sign up → API key.
   - **Resend** (email, free tier): sign up → API key. Use `onboarding@resend.dev` as the
     sender until you verify your own domain.
   - **Neon or Supabase** (free Postgres): create a project → copy the connection string.
3. In the repo: **Settings → Secrets and variables → Actions → New repository secret**, add:

   | Secret | Example |
   |---|---|
   | `TRAVELPAYOUTS_TOKEN` | `xxxxxxxxxxxx` |
   | `SERPAPI_KEY` | `xxxxxxxxxxxx` |
   | `RESEND_API_KEY` | `re_xxxxxxxx` |
   | `DATABASE_URL` | `postgresql://user:pass@host/db?sslmode=require` |
   | `EMAIL_TO` | `you@example.com,team@example.com` |
   | `EMAIL_FROM` | `Flight Tracker <onboarding@resend.dev>` |

4. Edit `tracker/config.py`: set your `DESTINATIONS`, `DROP_PCT_TRIGGER`, optional
   `ABS_TARGET` per route, and `MAX_LIVE_CALLS`.
5. Done. It runs daily (see the cron in `.github/workflows/track.yml`) and can be triggered
   manually from the **Actions** tab. Even before email is configured, the run uploads
   `report.html` as a downloadable artifact.

> **GitHub Actions needs Postgres, not SQLite.** The runner's disk is wiped each run, so
> SQLite would forget yesterday's prices and change-detection would never fire. Set
> `DATABASE_URL` to your Neon/Supabase string. (SQLite is the local-testing default.)

## Run locally

```bash
pip install -r requirements.txt
export TRAVELPAYOUTS_TOKEN=... SERPAPI_KEY=... RESEND_API_KEY=...
export EMAIL_TO=you@example.com EMAIL_FROM="Flight Tracker <onboarding@resend.dev>"
# DATABASE_URL omitted -> uses local sqlite flights.db
python -m tracker.main          # writes report.html and (if configured) sends the email
```

## Verify / tune

- **Travelpayouts endpoint.** Cached prices come from Aviasales search history and can be
  sparse on thin routes — expect some routes to return little data. If a route comes back
  empty, check `tracker/clients.py`: try `depart_date` as `YYYY-MM-01` instead of `YYYY-MM`,
  and confirm the `/v1/prices/calendar` path and the `length` (stay-length) parameter against
  the current docs at <https://travelpayouts-data-api.readthedocs.io/>.
- **Round-trip vs split.** On Indian-domestic LCCs these are usually equal; the tracker
  flags the cases where they're not.
- **SerpApi budget.** Daily × `MAX_LIVE_CALLS=8` ≈ 240/month — at or above the free tier, so
  keep the cap modest or move to the $25/month (1,000 searches) plan if you want more
  live confirmations.
- **Cron is UTC and best-effort.** `0 1 * * *` is 06:30 IST; GitHub may delay it under load.
