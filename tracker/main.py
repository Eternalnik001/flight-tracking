"""Entry point. Run with:  python -m tracker.main"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from . import analyze, clients, config, report, security, storage


async def scan_cached(dests: list[str], months: list[int]) -> list[tuple[str, dict] | Exception]:
    """Fetch one-way calendars (outbound + return) per destination per month, concurrently.

    Returns (dest, {month: (out_ow, ret_ow)}). The cache only serves one-way
    records, so a cached round-trip price isn't available; round trips are built
    as "split" fares in analyze and confirmed live via SerpApi for candidates.
    """
    tp = clients.Travelpayouts(config.TRAVELPAYOUTS_TOKEN, config.CURRENCY, config.REQUEST_TIMEOUT)
    sem = asyncio.Semaphore(config.MAX_CONCURRENCY)

    async with httpx.AsyncClient(verify=clients.CA_BUNDLE) as client:
        async def for_dest(dest: str):
            async with sem:
                by_month: dict[int, tuple[dict, dict]] = {}
                for m in months:
                    ms = config.trip_month_str(m)
                    out_ow = await tp.one_way_calendar(client, config.ORIGIN, dest, ms)
                    ret_ow = await tp.one_way_calendar(client, dest, config.ORIGIN, ms)
                    by_month[m] = (out_ow, ret_ow)
                return dest, by_month

        return await asyncio.gather(*(for_dest(d) for d in dests), return_exceptions=True)


def main() -> None:
    security.require_secrets("TRAVELPAYOUTS_TOKEN")  # core scan can't run without it
    storage.init_db()
    storage.seed_watchlist_if_empty(config.ORIGIN, config.DESTINATIONS)
    dests = storage.load_watchlist(config.ORIGIN) or config.DESTINATIONS
    combos_by_month = {m: config.trip_combos(m) for m in config.TRIP_MONTHS}
    prev = storage.load_latest()

    results = asyncio.run(scan_cached(dests, config.TRIP_MONTHS))

    matrices: dict[str, list[dict]] = {}
    all_points: dict[tuple[str, str, str], float] = {}
    candidates: list[tuple[float, str, dict]] = []

    for res in results:
        if isinstance(res, Exception):
            security.safe_print(f"[scan] route failed: {res!r}")
            continue
        dest, by_month = res
        rows: list[dict] = []
        for m, (out_ow, ret_ow) in by_month.items():
            rows += analyze.build_rows(out_ow, ret_ow, {}, combos_by_month[m], prev, dest)
        matrices[dest] = rows
        all_points.update(analyze.points_from_rows(dest, rows))
        candidates += analyze.find_candidates(
            dest, rows, config.DROP_PCT_TRIGGER, config.ABS_TARGET.get(dest)
        )

    # Gated live confirmation: biggest drops first, capped to protect the SerpApi free tier.
    candidates.sort(key=lambda c: c[0])
    live_done = 0
    if config.SERPAPI_KEY:
        serp = clients.SerpApi(config.SERPAPI_KEY, config.CURRENCY.upper())
        for _score, dest, row in candidates:
            if live_done >= config.MAX_LIVE_CALLS:
                break
            try:
                row["live"] = serp.price(config.ORIGIN, dest, row["depart"], row["return"])
                live_done += 1
            except Exception as exc:  # noqa: BLE001 - one bad live call shouldn't kill the run
                security.safe_print(f"[live] {dest} {row['depart']} failed: {exc!r}")

    storage.save_snapshot(all_points)

    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = report.render(matrices, run_at, live_done, len(candidates))

    with open("report.html", "w", encoding="utf-8") as fh:  # artifact / local preview
        fh.write(html)

    subject = f"{config.EMAIL_SUBJECT_PREFIX} — {run_at}"
    report.send(html, subject)
    print(f"[done] routes={len(matrices)} candidates={len(candidates)} live={live_done}")


if __name__ == "__main__":
    main()
