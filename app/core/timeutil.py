"""Timezone and timestamp helpers.

Internal storage is always UTC. Source-reported timestamps keep their original offset so that
the provenance of a provider's local-time reporting is not silently rewritten.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dateutil import parser as _date_parser  # type: ignore[import-untyped]

__all__ = ["utc_now", "ensure_aware", "to_utc", "parse_timestamp", "unix_seconds"]


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime) -> datetime:
    """Attach UTC to a naive datetime; convert an aware one to UTC.

    Naive timestamps are interpreted as UTC rather than as server-local time, because provider
    payloads that omit an offset are treated as UTC and this is recorded via a quality flag by
    the caller.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_utc(value: datetime) -> datetime:
    """Normalise any datetime to timezone-aware UTC."""
    return ensure_aware(value)


def parse_timestamp(value: Any) -> datetime:
    """Parse an ISO-8601 or epoch timestamp into timezone-aware UTC.

    Raises:
        ValueError: if the value cannot be parsed or is not a real instant.
    """
    if value is None:
        raise ValueError("timestamp is required")

    if isinstance(value, datetime):
        return ensure_aware(value)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Guard against obviously nonsensical epochs (seconds vs milliseconds confusion).
        number = float(value)
        if number > 1e11:  # treat as milliseconds
            number /= 1000.0
        if number < 0:
            raise ValueError("timestamp must not be negative")
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"timestamp out of range: {value!r}") from exc

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("timestamp must not be empty")
        # A trailing 'Z' is valid ISO-8601 but rejected by some parsers; normalise it.
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = _date_parser.isoparse(text)
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"unparseable timestamp: {value!r}") from exc
        return ensure_aware(parsed)

    raise ValueError(f"unsupported timestamp type: {type(value).__name__}")


def unix_seconds(value: datetime) -> int:
    """Return an integer POSIX timestamp (UTC) for a datetime."""
    return int(ensure_aware(value).timestamp())
