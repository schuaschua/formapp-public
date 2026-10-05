"""Story 7.2/FORM-238: the nightly feedback job actually categorises rows (spine AD-17, AD-18,
AD-20), over the real ``api`` role (never a superuser) so migration 0019's ``app.job_scope`` policy
is exercised for real, not just reasoned about (same discipline as ``test_rls.py``)."""

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest

from jobs.feedback import _run
from tests.jobs.support import StubCategoryPort

Admin = Callable[[str], psycopg.Connection[Any]]

_LOGGER = "formapp.jobs.feedback"
_SAMPLES = json.loads(
    (Path(__file__).parent / "fixtures" / "feedback_samples.json").read_text()
)

_owner_seq = iter(range(1, 10_000))


def _insert(
    admin: Admin,
    dbname: str,
    *,
    owner_oid: str = "synthetic-owner",
    rating: int,
    comment: str | None = None,
    category: str | None = None,
    categorised_at: datetime | None = None,
) -> UUID:
    with admin(dbname) as connection:
        seq = next(_owner_seq)
        connection.execute(
            "INSERT INTO proposal "
            "(owner_oid, owner_seq, schema_version, status, created_at, updated_at) "
            "VALUES (%s, %s, 1, 'draft', now(), now())",
            (owner_oid, seq),
        )
        [(proposal_id,)] = connection.execute(
            "SELECT id FROM proposal WHERE owner_oid = %s AND owner_seq = %s",
            (owner_oid, seq),
        ).fetchall()
        connection.execute(
            "INSERT INTO proposal_feedback "
            "(proposal_id, rating, comment, given_by, at, category, categorised_at) "
            "VALUES (%s, %s, %s, 'agent', now(), %s, %s)",
            (proposal_id, rating, comment, category, categorised_at),
        )
    return proposal_id


def _row(admin: Admin, dbname: str, proposal_id: UUID) -> tuple[str | None, datetime | None]:
    with admin(dbname) as connection:
        row = connection.execute(
            "SELECT category, categorised_at FROM proposal_feedback WHERE proposal_id = %s",
            (str(proposal_id),),
        ).fetchone()
    assert row is not None
    return row[0], row[1]


def _finished_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    [record] = [
        r
        for r in caplog.records
        if r.name == _LOGGER and r.getMessage() == "feedback job finished"
    ]
    return record


@pytest.mark.parametrize("sample", _SAMPLES, ids=[s["expected_category"] for s in _SAMPLES])
def test_form_238_every_sample_category_is_stored_with_categorised_at(
    job_env: pytest.MonkeyPatch, admin: Admin, migrated_db: str, sample: dict[str, Any]
) -> None:
    """AC: every category in the closed list is reachable from a real model answer (AD-20)."""
    proposal_id = _insert(admin, migrated_db, rating=sample["rating"], comment=sample["comment"])
    port = StubCategoryPort({sample["comment"]: sample["expected_category"]})

    asyncio.run(_run(category_port=port))

    category, categorised_at = _row(admin, migrated_db, proposal_id)
    assert category == sample["expected_category"]
    assert categorised_at is not None
    assert port.calls == [(sample["rating"], sample["comment"])]


def test_form_238_a_rating_with_no_comment_never_reaches_the_port(
    job_env: pytest.MonkeyPatch, admin: Admin, migrated_db: str
) -> None:
    """AC: "a rating with no comment gets 'No comment' without a model call" (AD-20)."""
    proposal_id = _insert(admin, migrated_db, rating=4, comment=None)
    port = StubCategoryPort()

    asyncio.run(_run(category_port=port))

    category, categorised_at = _row(admin, migrated_db, proposal_id)
    assert category == "No comment"
    assert categorised_at is not None
    assert port.calls == []


def test_form_238_a_whitespace_only_comment_is_treated_as_no_comment(
    job_env: pytest.MonkeyPatch, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert(admin, migrated_db, rating=3, comment="   ")
    port = StubCategoryPort()

    asyncio.run(_run(category_port=port))

    category, _ = _row(admin, migrated_db, proposal_id)
    assert category == "No comment"
    assert port.calls == []


def test_form_238_an_answer_outside_the_closed_list_is_stored_as_other(
    job_env: pytest.MonkeyPatch, admin: Admin, migrated_db: str
) -> None:
    """AC: "the model answers outside the list ... an unknown answer is stored as Other" (AD-20)."""
    proposal_id = _insert(admin, migrated_db, rating=1, comment="synthetic-comment")
    port = StubCategoryPort({"synthetic-comment": "Not A Real Category"})

    asyncio.run(_run(category_port=port))

    category, _ = _row(admin, migrated_db, proposal_id)
    assert category == "Other"


def test_form_238_a_failed_row_stays_null_and_the_job_continues_with_the_rest(
    job_env: pytest.MonkeyPatch,
    admin: Admin,
    migrated_db: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC: "a failure leaves the row NULL for the next night's run; the job continues with the
    rest" (AD-20)."""
    failing = _insert(admin, migrated_db, rating=2, comment="will-fail")
    ok = _insert(admin, migrated_db, rating=5, comment="will-succeed")
    port = StubCategoryPort(
        {"will-succeed": "Praise"}, fail_for=frozenset({"will-fail"})
    )

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        asyncio.run(_run(category_port=port))

    failed_category, failed_at = _row(admin, migrated_db, failing)
    assert failed_category is None
    assert failed_at is None
    ok_category, ok_at = _row(admin, migrated_db, ok)
    assert ok_category == "Praise"
    assert ok_at is not None

    record = _finished_record(caplog)
    assert record.pending == 2  # type: ignore[attr-defined]
    assert record.categorised == 1  # type: ignore[attr-defined]


def test_form_238_a_rerun_does_not_resend_an_already_categorised_row(
    job_env: pytest.MonkeyPatch, admin: Admin, migrated_db: str
) -> None:
    already_at = datetime(2026, 9, 1, tzinfo=UTC)
    already = _insert(
        admin,
        migrated_db,
        rating=5,
        comment="already categorised",
        category="Praise",
        categorised_at=already_at,
    )
    fresh = _insert(admin, migrated_db, rating=3, comment="not yet categorised")
    port = StubCategoryPort({"not yet categorised": "Understanding"})

    asyncio.run(_run(category_port=port))

    assert port.calls == [(3, "not yet categorised")]
    already_category, already_categorised_at = _row(admin, migrated_db, already)
    assert already_category == "Praise"
    assert already_categorised_at == already_at
    fresh_category, _ = _row(admin, migrated_db, fresh)
    assert fresh_category == "Understanding"


def test_form_238_reads_and_writes_across_owners(
    job_env: pytest.MonkeyPatch, admin: Admin, migrated_db: str
) -> None:
    """The job runs as the same ``api`` role REST/MCP use (AD-20), whose default AD-17 scopes only
    ever grant one owner or one proposal -- migration 0019's ``app.job_scope`` policy is what makes
    a single run reach every owner's pending rows at all."""
    owner_a = _insert(
        admin, migrated_db, owner_oid="synthetic-owner-a", rating=4, comment="owner a's comment"
    )
    owner_b = _insert(
        admin, migrated_db, owner_oid="synthetic-owner-b", rating=2, comment="owner b's comment"
    )
    port = StubCategoryPort(
        {"owner a's comment": "Speed", "owner b's comment": "Voice"}
    )

    asyncio.run(_run(category_port=port))

    assert _row(admin, migrated_db, owner_a)[0] == "Speed"
    assert _row(admin, migrated_db, owner_b)[0] == "Voice"
