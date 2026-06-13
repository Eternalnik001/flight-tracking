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


def _dedupe_live(items: list[tuple[str, str, float]]) -> list[tuple[str, str, float]]:
    """Collapse duplicate (dest, depart) live prices, keeping the cheapest.

    A candidate confirmation and a backfill could in principle target the same
    route-day; `latest` is keyed on (dest, depart, 'live'), so we must not hand
    `save_live` two rows for the same key.
    """
    best: dict[tuple[str, str], float] = {}
    for dest, depart, price in items:
        if (dest, depart) not in best or price < best[(dest, depart)]:
            best[(dest, depart)] = price
    return [(dest, depart, price) for (dest, depart), price in best.items()]


def _backfill_empty_routes(serp, matrices, out: list, budget: int) -> int:
    """Live-fetch one round-trip price for each (dest, month) the cache left empty.

    Skips route-months that already have a *fresh* live price (< LIVE_STALE_DAYS old)
    so the budget isn't re-spent daily. Appends (dest, depart_iso, price) to `out`.
    Returns the number of live calls spent.
    """
    if budget <= 0:
        return 0
    ages = storage.load_live_ages()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    todo: list[tuple[str, str, str]] = []
    for dest, rows in matrices.items():
        for m in config.TRIP_MONTHS:
            mm = f"{m:02d}"
            if any(r["best_price"] is not None and r["depart"][5:7] == mm for r in rows):
                continue  # cache already has a round trip this month
            dep, ret = config.sample_combo(m)
            dep_iso, ret_iso = dep.isoformat(), ret.isoformat()
            age = ages.get((dest, dep_iso))
            if age is not None and (now - age.replace(tzinfo=None)).days < config.LIVE_STALE_DAYS:
                continue  # fresh live price already stored
            todo.append((dest, dep_iso, ret_iso))

    spent = filled = 0
    for dest, dep_iso, ret_iso in todo:
        if spent >= budget:
            print(f"[backfill] budget reached — {len(todo) - spent} route-month(s) deferred to a later run")
            break
        try:
            res = serp.price(config.ORIGIN, dest, dep_iso, ret_iso)
            if res.get("price") is not None:
                out.append((dest, dep_iso, float(res["price"])))
                filled += 1
            spent += 1
        except Exception as exc:  # noqa: BLE001 - one bad call shouldn't kill the run
            security.safe_print(f"[backfill] {dest} {dep_iso} failed: {exc!r}")
    if filled:
        print(f"[backfill] filled {filled} empty route-month(s) with live prices")
    return spent


def main() -> None:
    security.require_secrets("TRAVELPAYOUTS_TOKEN")  # core scan can't run without it
    storage.init_db()
    storage.seed_watchlist_if_fresh(config.ORIGIN, config.DESTINATIONS)
    dests = storage.load_watchlist(config.ORIGIN)
    if not dests:
        print("[scan] watchlist is empty — add destinations in the dashboard. Nothing to scan.")
        return
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

    # Live SerpApi calls (capped by MAX_LIVE_CALLS to protect the free tier):
    #   1) confirm the biggest cached price drops, then
    #   2) backfill routes/months the free cache left empty, so they aren't blank.
    candidates.sort(key=lambda c: c[0])
    live_done = 0
    # Live round-trip prices to persist (dest, depart_iso, price). Both the gated
    # candidate confirmations AND the empty-route backfill land here, so the
    # dashboard sees every live price we paid for — not just the backfill.
    live_results: list[tuple[str, str, float]] = []
    if config.SERPAPI_KEY:
        serp = clients.SerpApi(config.SERPAPI_KEY, config.CURRENCY.upper())

        for _score, dest, row in candidates:
            if live_done >= config.MAX_LIVE_CALLS:
                break
            try:
                row["live"] = serp.price(config.ORIGIN, dest, row["depart"], row["return"])
                live_done += 1
                price = (row["live"] or {}).get("price")
                if price is not None:
                    live_results.append((dest, row["depart"], float(price)))
            except Exception as exc:  # noqa: BLE001 - one bad live call shouldn't kill the run
                security.safe_print(f"[live] {dest} {row['depart']} failed: {exc!r}")

        live_done += _backfill_empty_routes(
            serp, matrices, live_results, budget=config.MAX_LIVE_CALLS - live_done
        )

    storage.save_snapshot(all_points)
    storage.save_live(_dedupe_live(live_results))
    pruned = storage.prune_history(config.HISTORY_RETENTION_DAYS)
    if pruned:
        print(f"[prune] removed {pruned} history row(s) older than {config.HISTORY_RETENTION_DAYS}d")

    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = report.render(matrices, run_at, live_done, len(candidates))
    with open("report.html", "w", encoding="utf-8") as fh:  # artifact / local preview
        fh.write(html)
    print(f"[done] routes={len(matrices)} candidates={len(candidates)} live={live_done}")


if __name__ == "__main__":
    main()
