"""Test doubles for `jobs.ports` (Story 7.2/FORM-238, Story 7.3/FORM-239, spine AD-18): no test
calls Foundry or Storage."""

from jobs.ports import CategoryPortError, SnapshotExportPortError


class StubCategoryPort:
    """A scripted `CategoryPort`. `answers` maps a comment to the raw answer to return for it (an
    exact match, falling back to `default` otherwise); `fail_for` names comments that raise
    `CategoryPortError` instead. `calls` records every `(rating, comment)` pair actually asked for,
    so a test can assert a no-comment row never reaches this port at all."""

    def __init__(
        self,
        answers: dict[str, str] | None = None,
        *,
        fail_for: frozenset[str] = frozenset(),
        default: str = "Other",
    ) -> None:
        self._answers = answers or {}
        self._fail_for = fail_for
        self._default = default
        self.calls: list[tuple[int, str]] = []

    async def categorise(self, *, rating: int, comment: str) -> str:
        self.calls.append((rating, comment))
        if comment in self._fail_for:
            raise CategoryPortError("synthetic failure")
        return self._answers.get(comment, self._default)


class StubSnapshotExportPort:
    """A scripted `SnapshotExportPort` (Story 7.3/FORM-239). Records every `write_snapshot` call's
    rows in `calls`, so a test can assert what the job would have exported without ever reaching
    Storage; `fail` makes the call raise `SnapshotExportPortError` instead, the way a real Storage
    outage would."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.calls: list[list[dict[str, object]]] = []

    async def write_snapshot(self, rows: list[dict[str, object]]) -> None:
        self.calls.append(rows)
        if self._fail:
            raise SnapshotExportPortError("synthetic failure")
