"""The stored ``answer_overrides`` row (Story 4.9, AD-17, security.md rule 37/31): read/write-side
table description plus a bulk insert helper, used from inside ``SqlProposalStore.update_answers``'s
own transaction/connection so the override rows commit or roll back together with the proposal
``UPDATE`` they log (AD-17's "the override write fails, the whole transaction rolls back").

A separate module from ``adapters/db/proposals.py`` (implementer's call per the FORM-30 brief): the
table this describes is created and RLS-fenced entirely in migration 0012, so nothing here needs to
touch that shared file beyond ``update_answers`` itself.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import Column, FetchedValue, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncConnection

from domain.answer_overrides import AnswerOverride

_metadata = MetaData()

# Read/write-side description of the table migration 0012 creates. `id`'s actual default
# (gen_random_uuid()) is defined once, in the migration; FetchedValue only tells SQLAlchemy one
# exists, so `insert()` never has to pass it (mirrors proposal_table's own convention).
answer_overrides_table = Table(
    "answer_overrides",
    _metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True, server_default=FetchedValue()),
    Column("proposal_id", PGUUID(as_uuid=True), nullable=False),
    Column("question_id", Text, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("previous_value", JSONB),
    Column("previous_source", Text),
    Column("new_value", JSONB),
    Column("model_deployment", Text, nullable=False),
    Column("overridden_by", Text, nullable=False),
    Column("at", sa.TIMESTAMP(timezone=True), nullable=False),
)


async def insert_overrides(
    connection: AsyncConnection, overrides: Sequence[AnswerOverride]
) -> None:
    """Insert every row from :func:`domain.answer_overrides.overrides_for` on ``connection``, in
    whatever transaction the caller already has open. A no-op for an empty sequence (the common
    case: AC4's no-row writes), never issuing an empty ``INSERT``."""
    if not overrides:
        return
    await connection.execute(
        sa.insert(answer_overrides_table),
        [
            {
                "proposal_id": override.proposal_id,
                "question_id": override.question_id,
                "schema_version": override.schema_version,
                "previous_value": override.previous_value,
                "previous_source": override.previous_source,
                "new_value": override.new_value,
                "model_deployment": override.model_deployment,
                "overridden_by": override.overridden_by,
                "at": override.at,
            }
            for override in overrides
        ],
    )
