"""Test doubles for the AD-18 seams."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


class FakeClock:
    """A settable clock: tests move time instead of sleeping (spine AD-18)."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 9, 26, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value

    def advance(self, delta: timedelta) -> None:
        self._now += delta


@dataclass
class FakeAccessToken:
    token: str
    expires_on: int


class FakeCredential:
    """Stands in for ManagedIdentityCredential; never reaches Azure."""

    def __init__(
        self, clock: FakeClock, lifetime: timedelta = timedelta(hours=1)
    ) -> None:
        self._clock = clock
        self._lifetime = lifetime
        self.scopes: list[tuple[str, ...]] = []

    def get_token(self, *scopes: str) -> FakeAccessToken:
        self.scopes.append(scopes)
        expires = self._clock.now() + self._lifetime
        return FakeAccessToken(
            token=f"synthetic-entra-token-{len(self.scopes)}",
            expires_on=int(expires.timestamp()),
        )
