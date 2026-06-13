"""Unit tests for history retention and the live-dedupe helper."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, insert, select

from tracker import main, storage


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    monkeypatch.setattr(storage, "ENGINE", engine)
    storage._metadata.create_all(engine)
    return engine


def test_prune_history_removes_only_old_rows(temp_db):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=400)
    with temp_db.begin() as conn:
        conn.execute(insert(storage.history), [
            {"dest": "DEL", "depart": "2026-08-01", "fare_type": "cheapest", "price": 1.0, "run_at": old},
            {"dest": "DEL", "depart": "2026-08-01", "fare_type": "cheapest", "price": 2.0, "run_at": now},
        ])

    removed = storage.prune_history(retention_days=180)
    assert removed == 1
    with temp_db.connect() as conn:
        remaining = conn.execute(select(storage.history.c.price)).fetchall()
    assert [r.price for r in remaining] == [2.0]


def test_prune_history_disabled_with_zero(temp_db):
    with temp_db.begin() as conn:
        conn.execute(insert(storage.history), {
            "dest": "DEL", "depart": "2026-08-01", "fare_type": "cheapest", "price": 1.0,
            "run_at": datetime.now(timezone.utc) - timedelta(days=9999),
        })
    assert storage.prune_history(0) == 0


def test_dedupe_live_keeps_cheapest():
    items = [("DEL", "2026-08-15", 6000.0), ("DEL", "2026-08-15", 5500.0), ("BOM", "2026-08-15", 4000.0)]
    out = dict(((d, dep), p) for d, dep, p in main._dedupe_live(items))
    assert out[("DEL", "2026-08-15")] == 5500.0
    assert out[("BOM", "2026-08-15")] == 4000.0
