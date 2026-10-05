"""Per-``oid`` chat-turn throttle (Story 4.8, spine AD-9, AD-17, AD-18).

Each insurance agent (``oid``) may start at most :data:`THROTTLE_LIMIT` chat turns in any rolling
:data:`THROTTLE_WINDOW`, across every proposal and every replica -- counted in PostgreSQL (AD-9),
never in memory, with the current time always taken from the injectable :class:`~domain.clock.Clock`
(AD-18), never SQL ``now()``. :func:`check_and_record` is called before any lock is taken (before
``adapters.chat.turns.open_chat_turn``), so a throttled request takes no lock and is never counted
towards a future check; an allowed call records its own start time in the same call, atomically,
so two turns racing for the same ``oid`` can't both slip past the limit.
"""

from datetime import datetime, timedelta
from math import ceil
from typing import Protocol

from domain.clock import Clock

# Story 4.8, AD-9: "each insurance agent (oid) may start at most 3 turns in any rolling 10 seconds".
THROTTLE_WINDOW = timedelta(seconds=10)
THROTTLE_LIMIT = 3


class ThrottledError(Exception):
    """Raised by :func:`check_and_record` when ``oid`` is over the limit (Story 4.8, AD-9): a
    dedicated 429 response carries ``retry_after_seconds``, never squeezed into the AD-12
    ``FieldError``/``DomainError`` shape, which has no room for it (spec Boundaries)."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Throttled; retry after {retry_after_seconds}s.")
        self.retry_after_seconds = retry_after_seconds


class ThrottleStore(Protocol):
    """Port to the stored per-``oid`` turn-start timestamps (``chat_turn_log``, migration 0017);
    implemented by the db adapter."""

    async def record_if_allowed(
        self, oid: str, now: datetime, window_start: datetime, limit: int
    ) -> datetime | None:
        """Atomically, in one transaction: if fewer than ``limit`` turns for ``oid`` started at or
        after ``window_start``, insert one more at ``now`` and return ``None`` (allowed, recorded);
        otherwise insert nothing and return the earliest of those turns' ``started_at`` (throttled,
        not recorded) -- Story 4.8's "refused requests do not count as turns"."""
        ...


async def check_and_record(store: ThrottleStore, oid: str, clock: Clock) -> None:
    """Story 4.8 AC1/AC-window-slide/AC-refused-not-counted: raises :class:`ThrottledError` when
    ``oid`` already started :data:`THROTTLE_LIMIT` turns in the rolling :data:`THROTTLE_WINDOW`
    (``retry_after_seconds`` is the ceiling of the seconds until the oldest of those leaves the
    window, at least 1); otherwise records this turn's start and returns normally. ``oid`` alone is
    the key, across every proposal and replica -- there is no per-proposal turn limit."""
    now = clock.now()
    oldest = await store.record_if_allowed(
        oid, now, now - THROTTLE_WINDOW, THROTTLE_LIMIT
    )
    if oldest is not None:
        retry_after = (oldest + THROTTLE_WINDOW) - now
        raise ThrottledError(max(1, ceil(retry_after.total_seconds())))
