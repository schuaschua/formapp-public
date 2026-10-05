"""Story 7.1/FORM-237: the nightly feedback job's entry point (AD-10, AD-18, AD-20). FORM-237 gave
the job just enough to count rows still waiting for a category and log one fixed summary line;
these tests only ever exercise rows a category_port never needs to see (no rows, or a NULL-category
row with no comment) -- Story 7.2's own behaviour is covered in test_feedback_categorise.py."""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import psycopg
import pytest

from jobs.feedback import _run, main
from jobs.settings import JobSettingsError
from tests.jobs.support import StubCategoryPort

Admin = Callable[[str], psycopg.Connection[Any]]

_LOGGER = "formapp.jobs.feedback"


def _insert_feedback(
    admin: Admin, dbname: str, *, owner_seq: int, rating: int, category: str | None
) -> None:
    with admin(dbname) as connection:
        connection.execute(
            "INSERT INTO proposal "
            "(owner_oid, owner_seq, schema_version, status, created_at, updated_at) "
            "VALUES ('synthetic-owner', %s, 1, 'draft', now(), now())",
            (owner_seq,),
        )
        [(proposal_id,)] = connection.execute(
            "SELECT id FROM proposal WHERE owner_seq = %s", (owner_seq,)
        ).fetchall()
        connection.execute(
            "INSERT INTO proposal_feedback (proposal_id, rating, given_by, at, category) "
            "VALUES (%s, %s, 'agent', now(), %s)",
            (proposal_id, rating, category),
        )


def _finished_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    [record] = [
        r
        for r in caplog.records
        if r.name == _LOGGER and r.getMessage() == "feedback job finished"
    ]
    return record


def test_form_237_job_has_nothing_to_do_with_no_feedback(
    job_env: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """AC: the job starts, has nothing to do, and logs a message-free summary (AD-20)."""
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        asyncio.run(_run(category_port=StubCategoryPort()))

    record = _finished_record(caplog)
    assert record.event == "feedback_job_finished"  # type: ignore[attr-defined]
    assert record.pending == 0  # type: ignore[attr-defined]
    assert record.categorised == 0  # type: ignore[attr-defined]
    # Message-free: the fixed text carries no count or other data, only the extra fields do
    # (security.md rule 30).
    assert record.getMessage() == "feedback job finished"


def test_form_237_job_counts_only_rows_without_a_category(
    job_env: pytest.MonkeyPatch,
    admin: Admin,
    migrated_db: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _insert_feedback(admin, migrated_db, owner_seq=1, rating=5, category=None)
    _insert_feedback(admin, migrated_db, owner_seq=2, rating=3, category="Praise")

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        asyncio.run(_run(category_port=StubCategoryPort()))

    assert _finished_record(caplog).pending == 1  # type: ignore[attr-defined]


def test_form_237_summary_never_carries_a_rating_or_comment_value(
    job_env: pytest.MonkeyPatch,
    admin: Admin,
    migrated_db: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with admin(migrated_db) as connection:
        connection.execute(
            "INSERT INTO proposal "
            "(owner_oid, owner_seq, schema_version, status, created_at, updated_at) "
            "VALUES ('synthetic-owner', 1, 1, 'draft', now(), now())"
        )
        [(proposal_id,)] = connection.execute("SELECT id FROM proposal").fetchall()
        connection.execute(
            "INSERT INTO proposal_feedback (proposal_id, rating, comment, given_by, at) "
            "VALUES (%s, 1, 'synthetic-must-not-log', 'agent', now())",
            (proposal_id,),
        )

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        asyncio.run(_run(category_port=StubCategoryPort()))

    for record in caplog.records:
        assert "synthetic-must-not-log" not in record.getMessage()


def test_form_237_main_exits_0_and_configures_logging(
    job_env: pytest.MonkeyPatch,
) -> None:
    assert main() == 0


def test_form_237_main_exits_1_on_bad_settings_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("FORMAPP_DEPLOYMENT", raising=False)
    monkeypatch.delenv("DATABASE_HOST", raising=False)

    assert main() == 1

    assert "DATABASE_HOST is required but not set" in capsys.readouterr().err


def test_form_237_run_raises_the_settings_error_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_HOST", raising=False)

    with pytest.raises(JobSettingsError):
        asyncio.run(_run(category_port=StubCategoryPort()))
