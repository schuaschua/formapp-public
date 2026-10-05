"""The injectable clock (spine AD-18).

Domain code never reads the system clock; it takes a ``Clock``. SQL never calls ``now()``: the
current time from the clock is passed in as a bound parameter.
"""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """A source of the current time."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...
