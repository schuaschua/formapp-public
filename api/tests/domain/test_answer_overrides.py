"""Story 4.9: the pure before/after diff behind ``answer_overrides`` (AD-17, security.md rule 37,
EXPERIENCE.md line 229)."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from domain.answer_overrides import AnswerOverride, overrides_for
from domain.proposals import Proposal, ProposalStatus

OWNER_A = "synthetic-owner-a"
MODEL_DEPLOYMENT = "synthetic-gpt-deployment"
OVERRIDDEN_BY = "synthetic-agent-oid"
NOW = datetime(2026, 9, 27, 9, 1, tzinfo=UTC)


def _proposal(
    *, answers: dict[str, dict[str, object]], schema_version: int = 1
) -> Proposal:
    at = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    return Proposal(
        id=uuid4(),
        customer_id=None,
        owner_oid=OWNER_A,
        owner_seq=1,
        schema_version=schema_version,
        status=ProposalStatus.DRAFT,
        revision=0,
        conversation_id=None,
        answers=answers,
        created_at=at,
        updated_at=at,
        lock_holder=None,
        lock_expires_at=None,
        current_turn_id=None,
        submitted_at=None,
    )


def _entry(value: object, source: str) -> dict[str, object]:
    return {"value": value, "source": source, "updated_at": "2026-09-27T09:00:00Z"}


def _overrides(before: Proposal, after: Proposal) -> list[AnswerOverride]:
    return overrides_for(
        before,
        after,
        model_deployment=MODEL_DEPLOYMENT,
        overridden_by=OVERRIDDEN_BY,
        now=NOW,
    )


def test_story_4_9_default_overridden_by_human_is_logged() -> None:
    before = _proposal(answers={"G1": _entry("No", "default")})
    after = replace(before, answers={"G1": _entry("Yes", "human")})

    [override] = _overrides(before, after)

    assert override.proposal_id == after.id
    assert override.question_id == "G1"
    assert override.schema_version == after.schema_version
    assert override.previous_value == "No"
    assert override.previous_source == "default"
    assert override.new_value == "Yes"
    assert override.model_deployment == MODEL_DEPLOYMENT
    assert override.overridden_by == OVERRIDDEN_BY
    assert override.at == NOW


def test_story_4_9_ai_answer_cleared_by_human_is_logged_with_a_null_new_value() -> None:
    before = _proposal(answers={"N7": _entry("a pack a day", "ai")})
    after = replace(before, answers={"N7": _entry(None, "human")})

    [override] = _overrides(before, after)

    assert override.previous_value == "a pack a day"
    assert override.previous_source == "ai"
    assert override.new_value is None


def test_story_4_9_db_answer_overridden_by_human_is_logged() -> None:
    before = _proposal(answers={"C1": _entry("Ally", "db")})
    after = replace(before, answers={"C1": _entry("Alicia", "human")})

    [override] = _overrides(before, after)

    assert override.previous_source == "db"
    assert override.previous_value == "Ally"
    assert override.new_value == "Alicia"


def test_story_4_9_already_human_source_logs_no_row() -> None:
    before = _proposal(answers={"C1": _entry("Ally", "human")})
    after = replace(before, answers={"C1": _entry("Alicia", "human")})

    assert _overrides(before, after) == []


def test_story_4_9_no_op_write_logs_no_row() -> None:
    # apply_answers never re-stamps source on a no-op (the value didn't change), so `after`'s
    # entry here is exactly what a real no-op write would leave: still source "default".
    before = _proposal(answers={"G1": _entry("No", "default")})
    after = replace(before, answers={"G1": _entry("No", "default")})

    assert _overrides(before, after) == []


def test_story_4_9_never_answered_before_logs_no_row() -> None:
    # [ASSUMPTION] (FORM-30 brief): before has no stored entry at all for this question -- nothing
    # is being corrected, so it doesn't serve "measure where the model gets answers wrong".
    before = _proposal(answers={})
    after = replace(before, answers={"C1": _entry("Ally", "human")})

    assert _overrides(before, after) == []


def test_story_4_9_multiple_overridden_questions_each_log_their_own_row() -> None:
    before = _proposal(
        answers={
            "G1": _entry("No", "default"),
            "C1": _entry("Ally", "ai"),
            "C13": _entry("Macbeal", "human"),
        }
    )
    after = replace(
        before,
        answers={
            "G1": _entry("Yes", "human"),
            "C1": _entry("Alicia", "human"),
            "C13": _entry("Macbeal", "human"),  # unchanged: stays human, no new row
        },
    )

    overrides = _overrides(before, after)

    assert {override.question_id for override in overrides} == {"G1", "C1"}


def test_story_4_9_no_incoming_changes_at_all_logs_no_rows() -> None:
    before = _proposal(
        answers={"G1": _entry("No", "default"), "C1": _entry("Ally", "human")}
    )
    after = before

    assert _overrides(before, after) == []
