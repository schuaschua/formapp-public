"""Compute the audit rows for a human answer edit over a previously non-human value (Story 4.9,
AD-17, security.md rule 37, EXPERIENCE.md line 229: "each time the agent changes an answer set by
the AI, a default or the customer records: proposal, question ID, the previous answer and its
source, the human's answer, when.").

Pure and framework-free (coding-style.md rule 9): this module only diffs a proposal's ``answers``
before and after one write, so it applies equally well to any pure step over ``Proposal`` objects.
The FORM-30 brief limits its actual use to the human REST PATCH path
(:func:`domain.proposals.apply_answers` / ``adapters.db.proposals.SqlProposalStore.update_answers``)
-- never :func:`domain.proposals.apply_agent_patch`, the AI/MCP path -- so ``domain/proposals.py``
itself needs no changes: :func:`apply_answers` already only (re)stamps ``source: "human"`` on an
entry when its value actually changed, so "the after entry is human" already implies "this write
just changed it", and the diff below needs nothing else from the caller to know that.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from domain.proposals import Proposal


@dataclass(frozen=True, slots=True)
class AnswerOverride:
    """One ``answer_overrides`` row (Story 4.9, AD-17): the previous (non-human) answer a human
    write just replaced."""

    proposal_id: UUID
    question_id: str
    schema_version: int
    previous_value: Any
    previous_source: str | None
    new_value: Any
    model_deployment: str
    overridden_by: str
    at: datetime


def overrides_for(
    before: Proposal,
    after: Proposal,
    *,
    model_deployment: str,
    overridden_by: str,
    now: datetime,
) -> list[AnswerOverride]:
    """One row per question now stored at ``source: "human"`` in ``after`` whose ``before`` entry
    existed and wasn't already ``source: "human"`` (the AC2/AC3 default/ai cases).

    [ASSUMPTION] (FORM-30 brief): a question with **no** stored entry at all in ``before`` (never
    answered -- no default, ai or db value to correct) logs nothing; there's nothing being
    corrected, so it doesn't serve "measure where the model gets answers wrong". A no-op write (the
    incoming value matches what's already stored) and a write over an already-``human`` value both
    also log nothing (AC4) -- but for free, not by a special case here: :func:`apply_answers` never
    re-stamps ``source`` in either situation, so ``after``'s entry isn't ``"human"`` (a no-op) or
    ``before``'s entry already was (already-human), and this function's own checks already skip
    both.
    """
    overrides: list[AnswerOverride] = []
    for question_id, after_entry in after.answers.items():
        if after_entry.get("source") != "human":
            continue
        before_entry = before.answers.get(question_id)
        if before_entry is None:
            continue
        if before_entry.get("source") == "human":
            continue
        overrides.append(
            AnswerOverride(
                proposal_id=after.id,
                question_id=question_id,
                schema_version=after.schema_version,
                previous_value=before_entry.get("value"),
                previous_source=before_entry.get("source"),
                new_value=after_entry.get("value"),
                model_deployment=model_deployment,
                overridden_by=overridden_by,
                at=now,
            )
        )
    return overrides
