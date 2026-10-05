"""Story 7.3/FORM-239: ``BlobSnapshotExportPort`` -- unit tests only, with a fake ``client``
injected (spine AD-18: never a real Storage call). Proves the CSV shape (header, column order, no
customer field, deterministic hashes) and the upload call (blob name, overwrite), not the real
``azure-storage-blob`` SDK's own behaviour.
"""

import asyncio
import csv
import io
from typing import Any

import pytest

from adapters.feedback.blob_export import BlobSnapshotExportPort
from jobs.ports import SnapshotExportPortError

_ROW: dict[str, object] = {
    "proposal_hash": "a" * 64,
    "submitted_at": "2026-09-28T02:00:00+00:00",
    "product_code": "P1_LIFE",
    "schema_version": 1,
    "rating": 5,
    "comment": "Great, fast tool",
    "category": "Praise",
    "agent_hash": "b" * 64,
}


class _FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    async def upload_blob(
        self, name: str, data: bytes, *, overwrite: bool = False
    ) -> None:
        self.calls.append({"name": name, "data": data, "overwrite": overwrite})
        if self._fail:
            raise RuntimeError("synthetic storage failure")


def _port(client: Any) -> BlobSnapshotExportPort:
    return BlobSnapshotExportPort(
        container_url="https://synthetic.blob.core.windows.net/feedback-export", client=client
    )


def test_write_snapshot_uploads_feedback_csv_and_overwrites() -> None:
    client = _FakeClient()
    port = _port(client)

    asyncio.run(port.write_snapshot([_ROW]))

    [call] = client.calls
    assert call["name"] == "feedback.csv"
    assert call["overwrite"] is True


def test_write_snapshot_csv_has_the_ad_20_column_order_and_one_data_row() -> None:
    client = _FakeClient()
    port = _port(client)

    asyncio.run(port.write_snapshot([_ROW]))

    [call] = client.calls
    text = call["data"].decode("utf-8")
    reader = csv.reader(io.StringIO(text))
    header, data_row = list(reader)
    assert header == [
        "proposal_hash",
        "submitted_at",
        "product_code",
        "schema_version",
        "rating",
        "comment",
        "category",
        "agent_hash",
    ]
    assert data_row == [
        "a" * 64,
        "2026-09-28T02:00:00+00:00",
        "P1_LIFE",
        "1",
        "5",
        "Great, fast tool",
        "Praise",
        "b" * 64,
    ]


def test_write_snapshot_with_no_rows_still_writes_a_header_only_csv() -> None:
    client = _FakeClient()
    port = _port(client)

    asyncio.run(port.write_snapshot([]))

    [call] = client.calls
    text = call["data"].decode("utf-8")
    lines = [line for line in text.splitlines() if line]
    assert len(lines) == 1


def test_write_snapshot_never_carries_a_customer_field_or_a_raw_oid() -> None:
    """AC: the snapshot has no customer name, DOB, ID number, contact detail or raw `oid` (FR65)."""
    client = _FakeClient()
    port = _port(client)
    row = dict(_ROW)
    row["given_by_must_not_appear"] = "synthetic-raw-oid-should-never-be-here"

    asyncio.run(port.write_snapshot([row]))

    [call] = client.calls
    text = call["data"].decode("utf-8")
    assert "synthetic-raw-oid-should-never-be-here" not in text
    for forbidden in ("first_name", "date_of_birth", "id_number", "email", "mobile"):
        assert forbidden not in text


def test_write_snapshot_raises_snapshot_export_port_error_on_any_sdk_failure() -> None:
    client = _FakeClient(fail=True)
    port = _port(client)

    with pytest.raises(SnapshotExportPortError):
        asyncio.run(port.write_snapshot([_ROW]))


def test_demo_mode_builds_the_real_managed_identity_credential() -> None:
    """Outage-lesson regression (mirrors adapters.feedback.test_foundry_category's own regression
    test): the production job entrypoint builds the real async ManagedIdentityCredential without
    making a call, so an import/constructor-level break shows up here, not at 02:00 in demo."""
    from azure.identity.aio import ManagedIdentityCredential

    from jobs.feedback import _default_snapshot_export_port
    from jobs.settings import JobSettings

    settings = JobSettings(
        formapp_deployment="local",
        database_host="synthetic-host",
        database_name="synthetic-db",
        database_user="synthetic-user",
        azure_client_id="00000000-1111-2222-3333-444444444444",
        feedback_export_container_url="https://synthetic.blob.core.windows.net/feedback-export",
        feedback_export_salt="synthetic-salt",
    )

    port = _default_snapshot_export_port(settings)

    assert isinstance(port, BlobSnapshotExportPort)
    assert isinstance(port._credential, ManagedIdentityCredential)  # noqa: SLF001
    asyncio.run(port._credential.close())  # noqa: SLF001
