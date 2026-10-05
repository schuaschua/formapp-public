"""Nightly feedback job entry point (Story 7.1 setup/FORM-237, Story 7.2/FORM-238, spine AD-10,
AD-18, AD-20).

``python -m jobs.feedback`` is the Container Apps Job's command (``infra/demo/foundation``), run on
its nightly schedule as the same managed identity ``api`` uses -- the only other reader of
PostgreSQL (AD-10). It connects, categorises every `proposal_feedback` row still waiting for one
(reruns touch only NULL categories), and logs one fixed, message-free summary line with counts in
structured fields (never a rating or comment value, security.md rule 30), then exits 0.

Categorising happens under the job's own deliberate, least-privilege row-level security scope
(``adapters.db.scope.for_job``, migration 0019's ``app.job_scope`` policy) -- never a
``SECURITY DEFINER`` function -- because AD-17's own ``app.proposal_id``/``app.owner_oid`` scopes
only ever grant one proposal or one owner, and this job needs every owner's NULL-category rows.

A rating with no comment gets "No comment" straight away, no model call. A comment goes to
`jobs.ports.CategoryPort`; an answer outside the closed list is stored as "Other"; a failed call
(`jobs.ports.CategoryPortError`) leaves that row NULL for the next run and the job carries on with
the rest.

After categorising, the job overwrites one CSV snapshot (Story 7.3/FORM-239, migration 0020, AD-20,
FR65) through `jobs.ports.SnapshotExportPort`: every submitted proposal's feedback row, with a
proposal hash, submitted date, product code, schema version, rating, comment, category and a salted
agent hash (`domain.feedback_export.salted_hash`) -- never a customer field, never a raw `oid`. A
failed export (`jobs.ports.SnapshotExportPortError`) logs a message-free warning and the job still
exits 0: the export always overwrites the whole file, so the next night's run simply tries again.
"""

import asyncio
import logging
import sys
from typing import Any

import sqlalchemy as sa

from adapters.clock import SystemClock
from adapters.db.engine import build_password_source, create_engine
from adapters.db.scope import for_job, install_scope, scoped
from adapters.logging_setup import configure_logging
from domain.clock import Clock
from domain.feedback_categories import FEEDBACK_CATEGORIES, NO_COMMENT_CATEGORY
from domain.feedback_export import salted_hash
from jobs.ports import (
    CategoryPort,
    CategoryPortError,
    SnapshotExportPort,
    SnapshotExportPortError,
)
from jobs.settings import JobSettings, JobSettingsError, load_job_settings

logger = logging.getLogger("formapp.jobs.feedback")

# AD-20: "reruns touch only NULL categories" -- both queries below share this predicate, so the
# "pending" count logged always matches what this (or the next) run still has to do.
_PENDING_COUNT = sa.text(
    "SELECT count(*) FROM proposal_feedback WHERE category IS NULL"
)
_PENDING_ROWS = sa.text(
    "SELECT proposal_id, rating, comment FROM proposal_feedback WHERE category IS NULL"
)
# The WHERE guards against writing over a row categorised by some other run since it was read.
_WRITE_CATEGORY = sa.text(
    "UPDATE proposal_feedback SET category = :category, categorised_at = :at "
    "WHERE proposal_id = :proposal_id AND category IS NULL"
)
# Story 7.3/AD-20: "for submitted proposals only" -- migration 0020's job-scope SELECT policy on
# `proposal` enforces the same filter again in the database, so this WHERE is defence in depth, not
# the only guard. The product code is P1's answer (domain.proposals.resolve_quote reads it the same
# way); no other proposal.answers key is ever selected, so no customer answer ever reaches Python.
_EXPORT_ROWS = sa.text(
    "SELECT pf.proposal_id, p.submitted_at, p.answers->>'P1' AS product_code, "
    "p.schema_version, pf.rating, pf.comment, pf.category, pf.given_by "
    "FROM proposal_feedback pf JOIN proposal p ON p.id = pf.proposal_id "
    "WHERE p.status = 'submitted'"
)


def _default_category_port(settings: JobSettings) -> CategoryPort:
    """The production `CategoryPort` (Story 7.2, AD-18, AD-20). Lazy imports, same reason
    `adapters.rest.app._default_agent_gateway` defers them: azure-identity's async transport needs
    aiohttp, and no test reaches this function at all (every test calls `_run` with its own stub)."""
    from azure.identity.aio import ManagedIdentityCredential

    from adapters.feedback.foundry import FoundryCategoryPort

    return FoundryCategoryPort(
        project_endpoint=settings.foundry_project_endpoint or "",
        agent_name=settings.foundry_agent_name or "",
        model=settings.foundry_model or "",
        credential=ManagedIdentityCredential(client_id=settings.azure_client_id)
        if settings.azure_client_id
        else None,
    )


def _default_snapshot_export_port(settings: JobSettings) -> SnapshotExportPort:
    """The production `SnapshotExportPort` (Story 7.3, AD-18, AD-20). Lazy imports, same reason
    `_default_category_port` defers them: azure-identity's async transport needs aiohttp, and no
    test reaches this function at all (every test calls `_run` with its own stub)."""
    from azure.identity.aio import ManagedIdentityCredential

    from adapters.feedback.blob_export import BlobSnapshotExportPort

    return BlobSnapshotExportPort(
        container_url=settings.feedback_export_container_url or "",
        credential=ManagedIdentityCredential(client_id=settings.azure_client_id)
        if settings.azure_client_id
        else None,
    )


def _export_row(row: Any, salt: str) -> dict[str, object]:
    """One `SnapshotExportPort.write_snapshot` row (Story 7.3, AD-20, FR65): a proposal hash and a
    salted agent hash (never the proposal id or `given_by` themselves), and nothing from
    `proposal.answers` beyond the product code already picked out by `_EXPORT_ROWS`."""
    submitted_at = row["submitted_at"]
    return {
        "proposal_hash": salted_hash(str(row["proposal_id"]), salt),
        "submitted_at": submitted_at.isoformat() if submitted_at is not None else "",
        "product_code": row["product_code"] or "",
        "schema_version": row["schema_version"],
        "rating": row["rating"],
        "comment": row["comment"] or "",
        "category": row["category"] or "",
        "agent_hash": salted_hash(row["given_by"], salt),
    }


def _has_comment(comment: str | None) -> bool:
    return comment is not None and comment.strip() != ""


async def _categorise_one(
    category_port: CategoryPort, *, rating: int, comment: str | None
) -> str | None:
    """One row's category, or ``None`` on a port failure (the caller leaves it NULL)."""
    if not _has_comment(comment):
        return NO_COMMENT_CATEGORY
    assert comment is not None  # narrows for mypy; _has_comment already checked it
    try:
        answer = await category_port.categorise(rating=rating, comment=comment)
    except CategoryPortError:
        logger.warning(
            "feedback categorisation failed",
            extra={"event": "feedback_categorise_failed"},
        )
        return None
    return answer if answer in FEEDBACK_CATEGORIES else "Other"


async def _run(
    *,
    category_port: CategoryPort,
    snapshot_export_port: SnapshotExportPort | None = None,
    clock: Clock | None = None,
) -> None:
    """``snapshot_export_port`` is ``None`` in every Story 7.2 test that only cares about
    categorising (Story 7.3 adds nothing to those): the export step below is skipped entirely, not
    silently stubbed. ``main`` (the real entry point) always passes the production port."""
    settings = load_job_settings()
    clock = clock or SystemClock()
    engine = create_engine(settings, build_password_source(settings, clock))
    install_scope(engine)
    exported = 0
    try:
        with scoped(for_job()):
            async with engine.connect() as connection:
                pending = (await connection.execute(_PENDING_COUNT)).scalar_one()
                rows = (await connection.execute(_PENDING_ROWS)).mappings().all()

            categorised = 0
            for row in rows:
                category = await _categorise_one(
                    category_port, rating=row["rating"], comment=row["comment"]
                )
                if category is None:
                    continue
                async with engine.begin() as connection:
                    result = await connection.execute(
                        _WRITE_CATEGORY,
                        {
                            "proposal_id": row["proposal_id"],
                            "category": category,
                            "at": clock.now(),
                        },
                    )
                if result.rowcount:
                    categorised += 1

            if snapshot_export_port is not None:
                async with engine.connect() as connection:
                    export_rows = (
                        (await connection.execute(_EXPORT_ROWS)).mappings().all()
                    )
                salt = (
                    settings.feedback_export_salt.get_secret_value()
                    if settings.feedback_export_salt
                    else ""
                )
                csv_rows = [_export_row(row, salt) for row in export_rows]
                try:
                    await snapshot_export_port.write_snapshot(csv_rows)
                except SnapshotExportPortError:
                    logger.warning(
                        "feedback export failed",
                        extra={"event": "feedback_export_failed"},
                    )
                else:
                    exported = len(csv_rows)
    finally:
        await engine.dispose()

    # Fixed message text; counts are structured fields, never interpolated into it (security.md
    # rule 30 -- consistent with adapters.chat.logging_events' turn/write log lines).
    logger.info(
        "feedback job finished",
        extra={
            "event": "feedback_job_finished",
            "pending": pending,
            "categorised": categorised,
            "exported": exported,
        },
    )


def main() -> int:
    configure_logging()
    try:
        settings = load_job_settings()
    except JobSettingsError as exc:
        # Never print a value, only the variable names (NFR17). stderr, not the logger: a bad
        # settings object is the one failure this module can't safely turn into a structured log
        # line (adapters.settings.load_settings' own callers report it the same way).
        print(str(exc), file=sys.stderr)
        return 1
    asyncio.run(
        _run(
            category_port=_default_category_port(settings),
            snapshot_export_port=_default_snapshot_export_port(settings),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
