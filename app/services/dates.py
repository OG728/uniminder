from __future__ import annotations

from datetime import datetime, timezone


def to_local(value: datetime) -> datetime:
    """Convert a naive UTC timestamp (as stored from Canvas) to local time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.astimezone()


def local_date(value: datetime):
    return to_local(value).date()
