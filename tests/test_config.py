"""Unit tests for trip-window maths."""
from __future__ import annotations

from datetime import date

from tracker import config


def test_trip_combos_count_for_august():
    # August has 31 days; with NIGHTS=3 the last valid depart is the 28th (return 31st).
    combos = config.trip_combos(8)
    assert combos[0] == (date(config.TRIP_YEAR, 8, 1), date(config.TRIP_YEAR, 8, 4))
    assert combos[-1] == (date(config.TRIP_YEAR, 8, 28), date(config.TRIP_YEAR, 8, 31))
    assert len(combos) == 31 - config.NIGHTS


def test_trip_combos_all_span_exactly_nights():
    for depart, ret in config.trip_combos(11):
        assert (ret - depart).days == config.NIGHTS


def test_trip_month_str():
    assert config.trip_month_str(8) == f"{config.TRIP_YEAR}-08"
    assert config.trip_month_str(11) == f"{config.TRIP_YEAR}-11"


def test_sample_combo_is_mid_month():
    combos = config.trip_combos(11)
    assert config.sample_combo(11) == combos[len(combos) // 2]
