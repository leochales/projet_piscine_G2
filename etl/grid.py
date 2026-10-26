"""Grille temporelle commune à la collecte, à l'amorçage et à silver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# Pas de la grille de mesures
STEP = timedelta(seconds=60)


def floor_to_step(ts: datetime) -> datetime:
    """Arrondit à la minute inférieure, en UTC."""
    ts = ts.astimezone(UTC)
    return ts.replace(second=0, microsecond=0)


def to_utc(ts: datetime) -> datetime:
    """Horodatage en UTC ; sans fuseau, il est lu comme de l'UTC (comme l'API Mock)."""
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
