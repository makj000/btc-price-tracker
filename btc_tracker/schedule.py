from __future__ import annotations

from datetime import datetime, timedelta, timezone


VALID_POLL_FREQUENCIES = (5, 10, 15, 30, 60, 120, 360)
VALID_POLL_FREQUENCY_ERROR = "Frequency must be one of: 5, 10, 15, 30 minutes, or 1, 2, 6 hours."


def is_valid_poll_frequency(minutes: int) -> bool:
    return minutes in VALID_POLL_FREQUENCIES


def coerce_poll_frequency(minutes: int) -> int:
    if is_valid_poll_frequency(minutes):
        return minutes
    return min(VALID_POLL_FREQUENCIES, key=lambda allowed: (abs(allowed - minutes), allowed))


def next_scheduled_check_at(reference: datetime, frequency_minutes: int) -> datetime:
    if not is_valid_poll_frequency(frequency_minutes):
        raise ValueError(VALID_POLL_FREQUENCY_ERROR)

    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    if frequency_minutes < 60:
        hour_start = reference.replace(minute=0, second=0, microsecond=0)
        next_minute = ((reference.minute // frequency_minutes) + 1) * frequency_minutes
        if next_minute >= 60:
            return hour_start + timedelta(hours=1)
        return hour_start + timedelta(minutes=next_minute)

    day_start = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    frequency_hours = frequency_minutes // 60
    next_hour = ((reference.hour // frequency_hours) + 1) * frequency_hours
    if next_hour >= 24:
        return day_start + timedelta(days=1)
    return day_start + timedelta(hours=next_hour)
