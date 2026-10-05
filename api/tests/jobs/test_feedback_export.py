"""Story 7.3/FORM-239: the nightly feedback job's snapshot export (spine AD-17, AD-18, AD-20),
over the real ``api`` role (never a superuser) so migration 0020's ``app.job_scope`` policy on
``proposal`` is exercised for real, not just reasoned about (same discipline as
``test_feedback_categorise.py``)."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb

from domain.feedback_export import salted_hash
from jobs.feedback import _run
from tests.jobs.support import StubCategoryPort, StubSnapshotExportPort

Admin = Callable[[str], psycopg.Connection[Any]]

_LOGGER = "formapp.jobs.feedback"
_SALT = "synthetic-export-salt"  # matches tests.jobs.conftest.job_env

_owner_seq = iter(range(20_000, 30_000))


def _insert_proposal(
    admin: Admin,
    dbname: str,
    *,
    owner_oid: str = "synthetic-owner",
    status: str = "submitted",
    submitted: bool = True,
    schema_version: int = 1,
    product_code: str | None = "P1_TERM_LIFE",
) -> UUID:
    with admin(dbname) as connection:
        seq = next(_owner_seq)
        answers: dict[str, Any] = {"P1": product_code} if product_code else {}
        connection.execute(
            "INSERT INTO proposal "
            "(owner_oid, owner_seq, schema_version, status, answers, created_at, updated_at, "
            "submitted_at) "
            "VALUES (%s, %s, %s, %s, %s, now(), now(), %s)",
            (
                owner_oid,
                seq,
                schema_version,
                status,
                Jsonb(answers),
                datetime.now(UTC) if submitted else None,
            ),
        )
        [(proposal_id,)] = connection.execute(
            "SELECT id FROM proposal WHERE owner_oid = %s AND owner_seq = %s",
            (owner_oid, seq),
        ).fetchall()
    return proposal_id


def _insert_feedback(
    admin: Admin,
    dbname: str,
    proposal_id: UUID,
    *,
    rating: int = 5,
    comment: str | None = "Great tool",
    given_by: str = "synthetic-agent-oid",
    category: str | None = "Praise",
) -> None:
    with admin(dbname) as connection:
        connection.execute(
            "INSERT INTO proposal_feedback "
            "(proposal_id, rating, comment, given_by, at, category, categorised_at) "
            "VALUES (%s, %s, %s, %s, now(), %s, now())",
            (proposal_id, rating, comment, given_by, category),
        )


def test_form_239_exports_a_submitted_proposals_feedback_row(
    job_env: pytest.MonkeyPatch, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_proposal(admin, migrated_db)
    _insert_feedback(admin, migrated_db, proposal_id)
    export_port = StubSnapshotExportPort()

    asyncio.run(
        _run(category_port=StubCategoryPort(), snapshot_export_port=export_port)
    )

    [rows] = export_port.calls
    [row] = rows
    assert row["proposal_hash"] == salted_hash(str(proposal_id), _SALT)
    assert row["agent_hash"] == salted_hash("synthetic-agent-oid", _SALT)
    assert row["product_code"] == "P1_TERM_LIFE"
    assert row["schema_version"] == 1
    assert row["rating"] == 5
    assert row["comment"] == "Great tool"
    assert row["category"] == "Praise"
    assert row["submitted_at"]


def test_form_239_excludes_draft_proposals(
    job_env: pytest.MonkeyPatch, admin: Admin, migrated_db: str
) -> None:
    """AC: "for submitted proposals only" (AD-20, FR65)."""
    proposal_id = _insert_proposal(admin, migrated_db, status="draft", submitted=False)
    _insert_feedback(admin, migrated_db, proposal_id)
    export_port = StubSnapshotExportPort()

    asyncio.run(
        _run(category_port=StubCategoryPort(), snapshot_export_port=export_port)
    )

    [rows] = export_port.calls
    assert rows == []


def test_form_239_never_carries_the_raw_proposal_id_or_the_raw_agent_oid(
    job_env: pytest.MonkeyPatch, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_proposal(admin, migrated_db)
    _insert_feedback(admin, migrated_db, proposal_id, given_by="synthetic-raw-agent-oid")
    export_port = StubSnapshotExportPort()

    asyncio.run(
        _run(category_port=StubCategoryPort(), snapshot_export_port=export_port)
    )

    [rows] = export_port.calls
    [row] = rows
    assert str(proposal_id) not in str(row.values())
    assert "synthetic-raw-agent-oid" not in str(row.values())
    assert set(row.keys()) == {
        "proposal_hash",
        "submitted_at",
        "product_code",
        "schema_version",
        "rating",
        "comment",
        "category",
        "agent_hash",
    }


def test_form_239_no_snapshot_export_port_skips_export_entirely(
    job_env: pytest.MonkeyPatch, admin: Admin, migrated_db: str
) -> None:
    """Story 7.2's own tests call `_run` with no `snapshot_export_port` at all; this proves that
    stays a real skip, not an accidental crash, now that Story 7.3 exists."""
    proposal_id = _insert_proposal(admin, migrated_db)
    _insert_feedback(admin, migrated_db, proposal_id)

    asyncio.run(_run(category_port=StubCategoryPort()))


def test_form_239_an_export_failure_is_logged_and_the_job_still_exits_cleanly(
    job_env: pytest.MonkeyPatch,
    admin: Admin,
    migrated_db: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    proposal_id = _insert_proposal(admin, migrated_db)
    _insert_feedback(admin, migrated_db, proposal_id)
    export_port = StubSnapshotExportPort(fail=True)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        asyncio.run(
            _run(category_port=StubCategoryPort(), snapshot_export_port=export_port)
        )

    assert any(
        r.getMessage() == "feedback export failed" and r.name == _LOGGER
        for r in caplog.records
    )
