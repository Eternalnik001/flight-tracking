"""Turn raw cached prices into matrix rows, choose the cheapest booking strategy,
and compute the run-over-run delta used for live-confirmation gating.
"""
from __future__ import annotations

from datetime import date


def build_rows(
    out_ow: dict[str, float],   # BLR -> dest, one-way per departure day
    ret_ow: dict[str, float],   # dest -> BLR, one-way per departure day (i.e. per return day)
    rt: dict[str, float],       # BLR -> dest, round-trip per departure day (N-night stay)
    combos: list[tuple[date, date]],
    prev: dict[tuple[str, str, str], float],
    dest: str,
) -> list[dict]:
    """One row per (depart, return) combo.

    "split"     = book two one-ways (outbound + return).
    "roundtrip" = a single round-trip booking.
    On Indian domestic LCCs these are usually equal; the value is catching when
    they are not.
    """
    rows: list[dict] = []
    for depart, ret in combos:
        dep_iso, ret_iso = depart.isoformat(), ret.isoformat()
        outbound = out_ow.get(dep_iso)
        return_ = ret_ow.get(ret_iso)
        roundtrip = rt.get(dep_iso)

        split = (outbound + return_) if (outbound is not None and return_ is not None) else None

        options: dict[str, float] = {}
        if split is not None:
            options["split"] = split
        if roundtrip is not None:
            options["roundtrip"] = roundtrip

        best_strategy, best_price = (None, None)
        if options:
            best_strategy = min(options, key=options.get)
            best_price = options[best_strategy]

        delta = delta_pct = None
        if best_price is not None:
            old = prev.get((dest, dep_iso, "cheapest"))
            if old:
                delta = best_price - old
                delta_pct = delta / old

        rows.append(
            {
                "depart": dep_iso,
                "return": ret_iso,
                "outbound": outbound,
                "return_leg": return_,
                "split": split,
                "roundtrip": roundtrip,
                "best_strategy": best_strategy,
                "best_price": best_price,
                "delta": delta,
                "delta_pct": delta_pct,
                "live": None,  # filled in later for gated candidates
            }
        )
    return rows


def points_from_rows(dest: str, rows: list[dict]) -> dict[tuple[str, str, str], float]:
    """Flatten a destination's rows into storable price points."""
    pts: dict[tuple[str, str, str], float] = {}
    for r in rows:
        for ft, val in (
            ("outbound", r["outbound"]),
            ("return", r["return_leg"]),
            ("split", r["split"]),
            ("roundtrip", r["roundtrip"]),
            ("cheapest", r["best_price"]),
        ):
            if val is not None:
                pts[(dest, r["depart"], ft)] = val
    return pts


def find_candidates(
    dest: str,
    rows: list[dict],
    drop_pct_trigger: float,
    abs_target: float | None,
) -> list[tuple[float, str, dict]]:
    """Rows worth confirming live: a big enough drop, or at/below an absolute target.

    Returned tuples sort ascending by score so the biggest drops come first.
    """
    out: list[tuple[float, str, dict]] = []
    for r in rows:
        price, dpct = r["best_price"], r["delta_pct"]
        if price is None:
            continue
        if dpct is not None and dpct <= -drop_pct_trigger:
            out.append((dpct, dest, r))
        elif abs_target is not None and price <= abs_target:
            out.append((-1.0, dest, r))  # force to the front
    return out
