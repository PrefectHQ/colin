"""Duration parsing and calendar-aligned staleness utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

# Duration parsing pattern: number followed by optional 'c' prefix and unit
# Matches: 1m, 1h, 7d, 1w, 1M, 1Q (elapsed) and 1cm, 1cd, 1cw, 1cM, 1cQ (calendar-aligned)
_DURATION_PATTERN = re.compile(r"^(\d+)(c?)([mhdwMQ])$")


@dataclass(frozen=True)
class CalendarDuration:
    """Represents a calendar-aligned duration for staleness checks.

    Unlike elapsed durations (timedelta/relativedelta), calendar durations
    check if a certain number of calendar boundaries have been crossed.

    For example:
    - `30cm`: stale at minute boundaries :00 and :30 of each hour
    - `1cd`: stale when calendar day changes
    - `3cM`: stale when 3 calendar months have passed
    """

    value: int
    """Number of calendar periods."""

    unit: str
    """Calendar unit: 'm' (minute), 'd' (day), 'w' (week), 'M' (month), 'Q' (quarter)."""

    def is_stale(self, compiled_at: datetime, now: datetime) -> bool:
        """Check if enough calendar periods have passed."""
        if self.unit == "m":
            # Count minute periods since Unix epoch
            # e.g., 30cm means boundaries at :00 and :30 of each hour
            compiled_minutes = int(compiled_at.timestamp() // 60)
            now_minutes = int(now.timestamp() // 60)
            compiled_period = compiled_minutes // self.value
            now_period = now_minutes // self.value
            return now_period > compiled_period
        elif self.unit == "h":
            # Count hour periods since Unix epoch
            compiled_hours = int(compiled_at.timestamp() // 3600)
            now_hours = int(now.timestamp() // 3600)
            compiled_period = compiled_hours // self.value
            now_period = now_hours // self.value
            return now_period > compiled_period
        elif self.unit == "d":
            # Stale when calendar day changes (only value=1 is allowed)
            return now.date() > compiled_at.date()
        elif self.unit == "w":
            # Stale when ISO week changes (only value=1 is allowed)
            compiled_week = compiled_at.isocalendar()
            now_week = now.isocalendar()
            return (now_week.year, now_week.week) > (
                compiled_week.year,
                compiled_week.week,
            )
        elif self.unit == "M":
            # Check if we've crossed into a new N-month period
            # e.g., 2cM divides year into 6 periods: Jan-Feb, Mar-Apr, etc.
            periods_per_year = 12 // self.value
            compiled_period = (
                compiled_at.year * periods_per_year + (compiled_at.month - 1) // self.value
            )
            now_period = now.year * periods_per_year + (now.month - 1) // self.value
            return now_period > compiled_period
        elif self.unit == "Q":
            # Check if we've crossed into a new N-quarter period
            # e.g., 2cQ divides year into 2 periods: Q1-Q2, Q3-Q4
            periods_per_year = 4 // self.value
            compiled_quarter = (compiled_at.month - 1) // 3
            now_quarter = (now.month - 1) // 3
            compiled_period = compiled_at.year * periods_per_year + compiled_quarter // self.value
            now_period = now.year * periods_per_year + now_quarter // self.value
            return now_period > compiled_period
        else:
            raise ValueError(f"Unknown calendar unit: {self.unit!r}")


# Type alias for all duration types
Duration = timedelta | relativedelta | CalendarDuration


def parse_duration(duration: str) -> Duration:
    """Parse a duration string into a duration object.

    Supported formats:
    - h: hours (e.g., '1h', '24h') - fixed timedelta
    - d: days (e.g., '1d', '7d') - fixed timedelta
    - w: weeks (e.g., '1w', '2w') - fixed timedelta
    - M: months (e.g., '1M', '3M') - calendar-aware relativedelta
    - Q: quarters (e.g., '1Q', '2Q') - calendar-aware relativedelta

    Calendar-aligned with 'c' prefix:
    - cd: calendar days (e.g., '1cd') - stale when calendar day changes
    - cw: calendar weeks (e.g., '1cw') - stale when calendar week changes
    - cM: calendar months (e.g., '3cM') - stale after 3 calendar months
    - cQ: calendar quarters (e.g., '1cQ') - stale when calendar quarter changes

    Args:
        duration: Duration string.

    Returns:
        timedelta for h/d/w, relativedelta for M/Q, CalendarDuration for c-prefixed.

    Raises:
        ValueError: If the duration string is invalid.
    """
    match = _DURATION_PATTERN.match(duration)
    if not match:
        raise ValueError(
            f"Invalid duration format: {duration!r}. "
            "Expected format like '1h', '7d', '1w', '1M', '1Q' or '1cd', '1cM', etc."
        )

    value = int(match.group(1))
    is_calendar = match.group(2) == "c"
    unit = match.group(3)

    # Calendar-aligned durations
    if is_calendar:
        if unit == "m" and 60 % value != 0:
            raise ValueError(
                f"Calendar-aligned minutes must divide evenly into 60, got {value}. "
                "Valid values: 1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60."
            )
        if unit == "h" and 24 % value != 0:
            raise ValueError(
                f"Calendar-aligned hours must divide evenly into 24, got {value}. "
                "Valid values: 1, 2, 3, 4, 6, 8, 12, 24."
            )
        if unit == "d" and value != 1:
            raise ValueError(
                f"Calendar-aligned days only supports value 1, got {value}. "
                "Use '1cd' for daily calendar boundaries."
            )
        if unit == "w" and value != 1:
            raise ValueError(
                f"Calendar-aligned weeks only supports value 1, got {value}. "
                "Use '1cw' for weekly calendar boundaries."
            )
        if unit == "M" and 12 % value != 0:
            raise ValueError(
                f"Calendar-aligned months must divide evenly into 12, got {value}. "
                "Valid values: 1, 2, 3, 4, 6, 12."
            )
        if unit == "Q" and 4 % value != 0:
            raise ValueError(
                f"Calendar-aligned quarters must divide evenly into 4, got {value}. "
                "Valid values: 1, 2, 4."
            )
        return CalendarDuration(value=value, unit=unit)

    # Elapsed durations
    if unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    elif unit == "w":
        return timedelta(weeks=value)
    elif unit == "M":
        return relativedelta(months=value)
    elif unit == "Q":
        return relativedelta(months=value * 3)
    else:
        raise ValueError(f"Unknown duration unit: {unit!r}")
