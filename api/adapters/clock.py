"""The production clock (spine AD-18); tests use a settable fake instead."""

from datetime import UTC, datetime


class SystemClock:
    """Reads the system clock. The only place in the service that does."""

    def now(self) -> datetime:
        return datetime.now(UTC)
