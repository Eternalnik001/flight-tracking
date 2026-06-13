"""Unit tests for the pure fare-strategy / change-detection logic."""
from __future__ import annotations

from datetime import date

from tracker import analyze


COMBOS = [(date(2026, 8, 1), date(2026, 8, 4)), (date(2026, 8, 2), date(2026, 8, 5))]


def _row(rows, depart):
    return next(r for r in rows if r["depart"] == depart)


def test_split_chosen_when_cheaper_than_roundtrip():
    out_ow = {"2026-08-01": 2000.0}
    ret_ow = {"2026-08-04": 2500.0}
    rt = {"2026-08-01": 5000.0}  # round trip pricier than 2x one-way (4500)
    rows = analyze.build_rows(out_ow, ret_ow, rt, COMBOS, {}, "DEL")
    r = _row(rows, "2026-08-01")
    assert r["split"] == 4500.0
    assert r["roundtrip"] == 5000.0
    assert r["best_strategy"] == "split"
    assert r["best_price"] == 4500.0


def test_roundtrip_chosen_when_cheaper():
    out_ow = {"2026-08-01": 3000.0}
    ret_ow = {"2026-08-04": 3000.0}
    rt = {"2026-08-01": 5200.0}
    rows = analyze.build_rows(out_ow, ret_ow, rt, COMBOS, {}, "DEL")
    r = _row(rows, "2026-08-01")
    assert r["best_strategy"] == "roundtrip"
    assert r["best_price"] == 5200.0


def test_split_needs_both_legs():
    out_ow = {"2026-08-01": 3000.0}  # no matching return leg
    rows = analyze.build_rows(out_ow, {}, {}, COMBOS, {}, "DEL")
    r = _row(rows, "2026-08-01")
    assert r["split"] is None
    assert r["best_price"] is None
    assert r["best_strategy"] is None


def test_delta_computed_against_previous_cheapest():
    out_ow = {"2026-08-01": 2000.0}
    ret_ow = {"2026-08-04": 2000.0}
    prev = {("DEL", "2026-08-01", "cheapest"): 5000.0}
    rows = analyze.build_rows(out_ow, ret_ow, {}, COMBOS, prev, "DEL")
    r = _row(rows, "2026-08-01")
    assert r["best_price"] == 4000.0
    assert r["delta"] == -1000.0
    assert r["delta_pct"] == -0.2


def test_points_from_rows_skips_none():
    out_ow = {"2026-08-01": 2000.0}
    ret_ow = {"2026-08-04": 2000.0}
    rows = analyze.build_rows(out_ow, ret_ow, {}, COMBOS, {}, "DEL")
    pts = analyze.points_from_rows("DEL", rows)
    assert pts[("DEL", "2026-08-01", "cheapest")] == 4000.0
    assert pts[("DEL", "2026-08-01", "split")] == 4000.0
    # the second combo has no return leg -> no points for it
    assert ("DEL", "2026-08-02", "cheapest") not in pts


def test_find_candidates_on_drop():
    rows = [{"best_price": 4000.0, "delta_pct": -0.15, "depart": "2026-08-01", "return": "2026-08-04"}]
    cands = analyze.find_candidates("DEL", rows, drop_pct_trigger=0.10, abs_target=None)
    assert len(cands) == 1
    assert cands[0][0] == -0.15  # score = delta_pct, sorts biggest drop first


def test_find_candidates_ignores_small_drop():
    rows = [{"best_price": 4000.0, "delta_pct": -0.05, "depart": "2026-08-01", "return": "2026-08-04"}]
    assert analyze.find_candidates("DEL", rows, drop_pct_trigger=0.10, abs_target=None) == []


def test_find_candidates_on_absolute_target():
    rows = [{"best_price": 3000.0, "delta_pct": None, "depart": "2026-08-01", "return": "2026-08-04"}]
    cands = analyze.find_candidates("DEL", rows, drop_pct_trigger=0.10, abs_target=3500.0)
    assert len(cands) == 1
    assert cands[0][0] == -1.0  # forced to the front
