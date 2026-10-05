"""The production ``SnapshotExportPort`` (Story 7.3/FORM-239, spine AD-18, AD-20): serialises the
job's export rows into one CSV and overwrites ``feedback.csv`` in the private ``feedback-export``
blob container with the ``azure-storage-blob`` async client, authenticated as the ``api`` managed
identity (``ManagedIdentityCredential``, no key or SAS) -- the same shape
``adapters.feedback.foundry.FoundryCategoryPort`` uses for its own Azure call.

Never exercised against real Azure in any test (no test may call Azure, spine AD-18); the unit
tests here inject a fake ``client`` instead, exactly the seam this class exposes for that purpose.
"""

import csv
import io
from typing import Any, Protocol

from jobs.ports import SnapshotExportPortError

_BLOB_NAME = "feedback.csv"
# Column order the AC and the architecture spine both give (Story 7.3, AD-20, FR65): no customer
# field is ever a member of this tuple.
_COLUMNS = (
    "proposal_hash",
    "submitted_at",
    "product_code",
    "schema_version",
    "rating",
    "comment",
    "category",
    "agent_hash",
)


class _TokenCredential(Protocol):
    async def get_token(self, *scopes: str) -> Any: ...


class _BlobClient(Protocol):
    async def upload_blob(
        self, name: str, data: bytes, *, overwrite: bool = ...
    ) -> Any: ...


def _to_csv(rows: list[dict[str, object]]) -> bytes:
    """One header row plus one row per export row, in ``_COLUMNS`` order; any column a row doesn't
    carry is left blank rather than raising, so a caller only ever needs to supply what it has."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=_COLUMNS, extrasaction="ignore", restval=""
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


class BlobSnapshotExportPort:
    """See this module's docstring. ``client``/``credential`` are constructor seams for tests
    (spine AD-18); production code (``jobs.feedback``) leaves ``client`` at its default and builds
    a real ``ManagedIdentityCredential``."""

    def __init__(
        self,
        *,
        container_url: str,
        credential: _TokenCredential | None = None,
        client: _BlobClient | None = None,
    ) -> None:
        self._container_url = container_url
        self._credential = credential
        self._client = client

    def _build_client(self) -> _BlobClient:
        # Lazy import, same reason FoundryCategoryPort/_default_category_port defer azure-identity's
        # async transport: it needs aiohttp, and no test reaches this method at all (every test
        # injects its own fake `client`).
        from azure.storage.blob.aio import ContainerClient

        return ContainerClient.from_container_url(
            self._container_url, credential=self._credential
        )

    async def write_snapshot(self, rows: list[dict[str, object]]) -> None:
        csv_bytes = _to_csv(rows)
        try:
            client = self._client or self._build_client()
            await client.upload_blob(_BLOB_NAME, csv_bytes, overwrite=True)
        except Exception as exc:  # noqa: BLE001 -- any SDK/network failure fails this run cleanly
            raise SnapshotExportPortError(
                "The feedback snapshot export failed."
            ) from exc
