"""State for change-detection. DB-agnostic via SQLAlchemy Core.

`latest`  – a full snapshot of the most recent run, replaced each run. We read it
            *before* overwriting so we can diff this run against the previous one.
`history` – append-only log for price trends over time.

Set DATABASE_URL to a Postgres URL in production (the snapshot must survive between
GitHub Actions runs). SQLite is fine for local testing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
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
    # Trend lookups are always "this route/day over time"; index it so they stay
    # fast as the log grows. run_at supports the retention prune.
    Index("ix_history_dest_depart", "dest", "depart"),
    Index("ix_history_run_at", "run_at"),
)

# Routes the daily job should scan. The frontend writes here; the job reads it.
# Origin is always BLR for now but stored explicitly so it's easy to generalise.
watchlist = Table(
    "watchlist",
    _metadata,
    Column("origin", String, primary_key=True),
    Column("dest", String, primary_key=True),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("added_at", DateTime),
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


def load_watchlist(origin: str) -> list[str]:
    """Enabled destinations for `origin`, in stable order. Empty if none set."""
    with ENGINE.connect() as conn:
        rows = conn.execute(
            select(watchlist.c.dest)
            .where(watchlist.c.origin == origin, watchlist.c.enabled.is_(True))
            .order_by(watchlist.c.dest)
        )
        return [r.dest for r in rows]


def seed_watchlist_if_fresh(origin: str, dests: list[str]) -> None:
    """Seed the watchlist from `dests` only on a brand-new database.

    "Brand-new" = the watchlist is empty AND no run has ever happened (history is
    empty). This makes a fresh deploy work out of the box, but never re-adds the
    defaults once the user has curated their list — even if they clear it to empty.
    """
    with ENGINE.begin() as conn:
        has_wl = conn.execute(
            select(watchlist.c.dest).where(watchlist.c.origin == origin).limit(1)
        ).first()
        has_history = conn.execute(select(history.c.dest).limit(1)).first()
        if has_wl is not None or has_history is not None:
            return
        now = datetime.now(timezone.utc)
        conn.execute(
            insert(watchlist),
            [{"origin": origin, "dest": d, "enabled": True, "added_at": now} for d in dests],
        )


def save_snapshot(points: dict[tuple[str, str, str], float]) -> None:
    """Replace the cached part of `latest` with this run, append to `history`.

    `live` rows (from the live backfill) are preserved — they persist across runs
    and are refreshed on their own staleness schedule, not wiped every scan.
    """
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
        conn.execute(delete(latest).where(latest.c.fare_type != "live"))
        if latest_rows:
            conn.execute(insert(latest), latest_rows)
        if history_rows:
            conn.execute(insert(history), history_rows)


def load_live_ages() -> dict[tuple[str, str], datetime]:
    """{(dest, depart): captured_at} for stored live prices — used for staleness."""
    with ENGINE.connect() as conn:
        rows = conn.execute(
            select(latest.c.dest, latest.c.depart, latest.c.captured_at)
            .where(latest.c.fare_type == "live")
        )
        return {(r.dest, r.depart): r.captured_at for r in rows}


def save_live(items: list[tuple[str, str, float]]) -> None:
    """Upsert live round-trip prices (dest, depart, price) into `latest` + log to `history`."""
    if not items:
        return
    now = datetime.now(timezone.utc)
    with ENGINE.begin() as conn:
        for dest, depart, price in items:
            conn.execute(
                delete(latest).where(
                    latest.c.dest == dest, latest.c.depart == depart, latest.c.fare_type == "live"
                )
            )
            conn.execute(insert(latest), {"dest": dest, "depart": depart, "fare_type": "live",
                                          "price": price, "captured_at": now})
            conn.execute(insert(history), {"dest": dest, "depart": depart, "fare_type": "live",
                                           "price": price, "run_at": now})


def prune_history(retention_days: int) -> int:
    """Delete history rows older than `retention_days`. Returns rows removed.

    `latest` is never touched — it's a single replaced snapshot. 0/negative
    retention disables pruning (keep everything).
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    with ENGINE.begin() as conn:
        result = conn.execute(delete(history).where(history.c.run_at < cutoff))
        return result.rowcount or 0
