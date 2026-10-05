"""Seams the nightly feedback job calls through (spine AD-18: one interface, a production
implementation and a test implementation each). Story 7.1 settled their shape. Story 7.2 gave
`CategoryPort` its production implementation (`adapters.feedback.foundry.FoundryCategoryPort`) and
call site in `jobs.feedback`. Story 7.3 gives `SnapshotExportPort` its production implementation
(`adapters.feedback.blob_export.BlobSnapshotExportPort`) and call site the same way.
"""

from typing import Protocol


class CategoryPortError(RuntimeError):
    """A `CategoryPort.categorise` call failed (Story 7.2, AD-20): `jobs.feedback` catches this,
    leaves that row's `category` NULL, and carries on with the rest -- the next run retries it."""


class CategoryPort(Protocol):
    """Classifies one feedback row into one of the closed AD-20 categories
    (`domain.feedback_categories.FEEDBACK_CATEGORIES`), over the Foundry Responses API with no
    tools and temperature 0. A rating with no comment never reaches this port at all -- the job
    assigns it "No comment" itself. The job, not this port, maps an answer outside the closed list
    to "Other"; a failed call raises `CategoryPortError`."""

    async def categorise(self, *, rating: int, comment: str) -> str:
        """Return the model's raw answer text (the job validates it against
        `domain.feedback_categories.FEEDBACK_CATEGORIES`). Raise `CategoryPortError` on failure."""
        ...


class SnapshotExportPortError(RuntimeError):
    """A `SnapshotExportPort.write_snapshot` call failed (Story 7.3, AD-20): `jobs.feedback` logs a
    message-free warning and carries on -- the export overwrites the whole file every run, so the
    next night's run simply tries again; nothing needs to be retried row by row."""


class SnapshotExportPort(Protocol):
    """Overwrites the one CSV snapshot in the private `feedback-export` container (AD-20) after a
    categorising run, with no customer data: a proposal hash, submitted date, product code, schema
    version, rating, comment, category and a salted agent hash. Raises `SnapshotExportPortError` on
    failure."""

    async def write_snapshot(self, rows: list[dict[str, object]]) -> None: ...
