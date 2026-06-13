"""State for change-detection. DB-agnostic via SQLAlchemy Core.

`latest`  – a full snapshot of the most recent run, replaced each run. We read it
            *before* overwriting so we can diff this run against the previous one.
`history` – append-only log for price trends over time.

Set DATABASE_URL to a Postgres URL in production (the snapshot must survive between
GitHub Actions runs). SQLite is fine for local testing.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    insert,
    select,
)

from . import config

_metadata = MetaData()

latest = Table(
    "latest",
    _metadata,
    Column("dest", String, primary_key=True),
    Column("depart", String, primary_key=True),      # ISO date of outbound
    Column("fare_type", String, primary_key=True),    # outbound|return|split|roundtrip|cheapest
    Column("price", Float),
    Column("captured_at", DateTime),
)

history = Table(
    "history",
    _metadata,
    Column("dest", String),
    Column("depart", String),
    Column("fare_type", String),
    Column("price", Float),
    Column("run_at", DateTime),
)


def _engine():
    url = config.DATABASE_URL
    # Normalise common Postgres URLs to the psycopg v3 driver SQLAlchemy expects.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, future=True)


ENGINE = _engine()


def init_db() -> None:
    _metadata.create_all(ENGINE)


def load_latest() -> dict[tuple[str, str, str], float]:
    """Previous run's prices keyed by (dest, depart, fare_type)."""
    with ENGINE.connect() as conn:
        rows = conn.execute(select(latest.c.dest, latest.c.depart, latest.c.fare_type, latest.c.price))
        return {(r.dest, r.depart, r.fare_type): r.price for r in rows if r.price is not None}


def save_snapshot(points: dict[tuple[str, str, str], float]) -> None:
    """Replace `latest` with this run, and append everything to `history`."""
    now = datetime.now(timezone.utc)
    latest_rows = [
        {"dest": d, "depart": dep, "fare_type": ft, "price": p, "captured_at": now}
        for (d, dep, ft), p in points.items()
    ]
    history_rows = [
        {"dest": d, "depart": dep, "fare_type": ft, "price": p, "run_at": now}
        for (d, dep, ft), p in points.items()
    ]
    with ENGINE.begin() as conn:
        conn.execute(delete(latest))
        if latest_rows:
            conn.execute(insert(latest), latest_rows)
        if history_rows:
            conn.execute(insert(history), history_rows)
