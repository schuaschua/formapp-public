"""Story 1.8: creation, ownership, naming and the AD-5 draft wire shape (AD-5, AD-8).

Story 2.2 Part B's ``resolve_quote``/``quote_view`` tests live here too, since they extend the
same draft-read domain service.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from domain.customer_fields import db_columns
from domain.errors import DomainError, ErrorCode
from domain.products import PolicyTerm, Product, ProductType, Rider
from domain.proposals import (
    AI_TURN_SAFETY_WINDOW,
    LOCK_DURATION,
    Proposal,
    ProposalNotFoundError,
    ProposalStatus,
    SubmitResult,
    acquire_lock,
    apply_agent_patch,
    apply_answers,
    begin_turn,
    create_draft,
    delete_draft,
    display_name,
    draft_view,
    end_turn,
    ensure_owned,
    link_customer,
    lock_view,
    quote_view,
    relative_holder,
    resolve_quote,
    start_chat_turn,
    submit_proposal,
    turn_bound,
    validate_proposal,
)
from domain.schema import latest_version, load_schema
from domain.turn_tokens import TurnTokenClaims
from tests.fakes import FakeClock

OWNER_A = "synthetic-owner-a"
OWNER_B = "synthetic-owner-b"

# Story 4.4: the caller's per-tab X-Session-Id (AD-16), reused as most tests' lock holder so
# existing PATCH/draft_view fixtures need no other change than passing it through.
SESSION_ID = "synthetic-session-a"
OTHER_SESSION_ID = "synthetic-session-b"

# Story 1.10's apply_answers tests validate against the real released schema, like Story 1.7's.
SCHEMA = load_schema(latest_version())


def _answers(**values: object) -> dict[str, dict[str, object]]:
    return {
        question_id: {
            "value": value,
            "source": "human",
            "updated_at": "2026-09-27T00:00:00Z",
        }
        for question_id, value in values.items()
    }


def _proposal(
    *,
    owner_oid: str = OWNER_A,
    owner_seq: int = 1,
    answers: dict[str, dict[str, object]] | None = None,
    status: ProposalStatus = ProposalStatus.DRAFT,
    schema_version: int | None = None,
    now: datetime | None = None,
    lock_holder: str | None = SESSION_ID,
    lock_expires_at: datetime | None = None,
    current_turn_id: UUID | None = None,
    submitted_at: datetime | None = None,
) -> Proposal:
    at = now or datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    # Held by SESSION_ID, far from expiry, unless a test asks otherwise (Story 4.4): apply_answers
    # now requires the caller to hold the lock, and most of these fixtures predate the lock.
    holds_until = (
        lock_expires_at
        if lock_expires_at is not None
        else (at + timedelta(days=1) if lock_holder is not None else None)
    )
    return Proposal(
        id=uuid4(),
        customer_id=None,
        owner_oid=owner_oid,
        owner_seq=owner_seq,
        schema_version=schema_version or latest_version(),
        status=status,
        revision=0,
        conversation_id=None,
        answers=answers or {},
        created_at=at,
        updated_at=at,
        lock_holder=lock_holder,
        lock_expires_at=holds_until,
        current_turn_id=current_turn_id,
        submitted_at=submitted_at,
    )


class FakeProposalStore:
    """An in-memory ProposalStore (spine AD-8) mirroring the db adapter's numbering rule."""

    def __init__(self, proposals: Sequence[Proposal] = ()) -> None:
        self._proposals: dict[UUID, Proposal] = {p.id: p for p in proposals}

    async def create(
        self,
        *,
        owner_oid: str,
        schema_version: int,
        answers: Mapping[str, Mapping[str, Any]],
        now: datetime,
    ) -> Proposal:
        previous = [
            p.owner_seq for p in self._proposals.values() if p.owner_oid == owner_oid
        ]
        proposal = _proposal(
            owner_oid=owner_oid,
            owner_seq=max(previous, default=0) + 1,
            schema_version=schema_version,
            answers=dict(answers),
            now=now,
        )
        self._proposals[proposal.id] = proposal
        return proposal

    async def get(self, proposal_id: UUID) -> Proposal | None:
        return self._proposals.get(proposal_id)

    async def list_for_owner(
        self, owner_oid: str, status: ProposalStatus
    ) -> Sequence[Proposal]:
        rows = [
            p
            for p in self._proposals.values()
            if p.owner_oid == owner_oid and p.status == status
        ]
        return sorted(rows, key=lambda p: p.created_at, reverse=True)

    async def update_answers(
        self,
        proposal_id: UUID,
        expected_revision: int,
        apply: Callable[[Proposal], Proposal | None],
        *,
        model_deployment: str = "test-model-deployment",
        overridden_by: str = "test-overridden-by",
    ) -> Proposal | None:
        """Mirrors the SQL adapter's revision-mismatch semantics (spec assumption), for pure-domain
        tests that never touch a real database. Story 4.9's override logging happens in the SQL
        adapter, not here, so ``model_deployment``/``overridden_by`` are accepted only to satisfy
        the ``ProposalStore`` protocol and are otherwise unused."""
        current = self._proposals.get(proposal_id)
        if current is None:
            return None
        updated = apply(current)
        if updated is None:
            return None
        self._proposals[proposal_id] = updated
        return updated

    async def acquire_lock(
        self,
        proposal_id: UUID,
        session_id: str,
        now: datetime,
        expires_at: datetime,
        take_over: bool,
    ) -> Proposal | None:
        """Mirrors the SQL adapter's CAS semantics (spec assumption), for a pure-domain test of
        :func:`acquire_lock` that never touches a real database (Story 4.4, AD-16)."""
        current = self._proposals.get(proposal_id)
        if current is None:
            return None
        free = current.lock_holder is None or (
            current.lock_expires_at is not None and current.lock_expires_at < now
        )
        takes_over = take_over and current.lock_holder != "ai"
        if free or current.lock_holder == session_id or takes_over:
            updated = replace(
                current,
                lock_holder=session_id,
                lock_expires_at=expires_at,
                current_turn_id=None,
            )
            self._proposals[proposal_id] = updated
            return updated
        return current

    async def apply_agent_patch(
        self,
        proposal_id: UUID,
        apply: Callable[[Proposal], Proposal | None],
    ) -> Proposal | None:
        """Mirrors the SQL adapter's no-precondition write (Story 4.3), for pure-domain tests."""
        current = self._proposals.get(proposal_id)
        if current is None:
            return None
        updated = apply(current)
        if updated is None:
            return None
        self._proposals[proposal_id] = updated
        return updated

    async def set_turn(
        self,
        proposal_id: UUID,
        *,
        lock_holder: str | None,
        lock_expires_at: datetime | None,
        current_turn_id: UUID | None,
    ) -> Proposal | None:
        """Mirrors the SQL adapter's direct write (Story 4.3), for pure-domain tests."""
        current = self._proposals.get(proposal_id)
        if current is None:
            return None
        updated = replace(
            current,
            lock_holder=lock_holder,
            lock_expires_at=lock_expires_at,
            current_turn_id=current_turn_id,
        )
        self._proposals[proposal_id] = updated
        return updated

    async def begin_chat_turn(
        self,
        proposal_id: UUID,
        apply: Callable[[Proposal], Proposal],
    ) -> Proposal | None:
        """Mirrors the SQL adapter's row-locked apply-and-write (Story 4.5), for pure-domain
        tests: no real row lock is needed here since these tests never run concurrently."""
        current = self._proposals.get(proposal_id)
        if current is None:
            return None
        updated = apply(current)
        self._proposals[proposal_id] = updated
        return updated

    async def ensure_conversation(self, proposal_id: UUID, conversation_id: str) -> str:
        """Mirrors the SQL adapter's conditional write (Story 4.5, AD-9)."""
        current = self._proposals[proposal_id]
        if current.conversation_id is None:
            self._proposals[proposal_id] = replace(
                current, conversation_id=conversation_id
            )
            return conversation_id
        return current.conversation_id

    async def submit(
        self,
        proposal_id: UUID,
        expected_revision: int,
        apply: Callable[[Proposal], Awaitable[SubmitResult | None]],
    ) -> Proposal | None:
        """Mirrors the SQL adapter's semantics (spec assumption), for pure-domain tests that never
        touch a real database (Story 3.3): the customer upsert and feedback insert aren't modelled
        here (no database to write them to), only the resulting proposal row."""
        current = self._proposals.get(proposal_id)
        if current is None:
            return None
        result = await apply(current)
        if result is None:
            return None
        self._proposals[proposal_id] = result.proposal
        return result.proposal

    async def delete(self, proposal_id: UUID, owner_oid: str) -> bool:
        """Mirrors the SQL adapter's delete (Story FORM-227), for pure-domain tests: removes the
        row only when it exists and is owned by ``owner_oid`` (the real store's RLS scope would
        otherwise just see zero rows), same as its real ``WHERE`` + row-level security do."""
        current = self._proposals.get(proposal_id)
        if current is None or current.owner_oid != owner_oid:
            return False
        del self._proposals[proposal_id]
        return True


def test_story_1_8_create_draft_pins_the_latest_schema() -> None:
    proposal = asyncio.run(create_draft(FakeProposalStore(), OWNER_A, FakeClock()))

    assert proposal.status is ProposalStatus.DRAFT
    assert proposal.revision == 0
    assert proposal.customer_id is None
    assert proposal.conversation_id is None
    assert proposal.owner_oid == OWNER_A
    assert proposal.schema_version == latest_version()
    assert proposal.owner_seq == 1


def test_story_1_8_two_creates_by_one_agent_number_up() -> None:
    store = FakeProposalStore()
    clock = FakeClock()

    first = asyncio.run(create_draft(store, OWNER_A, clock))
    second = asyncio.run(create_draft(store, OWNER_A, clock))

    assert (first.owner_seq, second.owner_seq) == (1, 2)
    assert display_name(first) == "Untitled_Proposal_001"
    assert display_name(second) == "Untitled_Proposal_002"


def test_story_1_8_two_agents_number_from_one_each() -> None:
    store = FakeProposalStore()
    clock = FakeClock()

    a = asyncio.run(create_draft(store, OWNER_A, clock))
    b = asyncio.run(create_draft(store, OWNER_B, clock))

    assert (a.owner_seq, b.owner_seq) == (1, 1)
    assert display_name(a) == display_name(b) == "Untitled_Proposal_001"


def test_story_1_8_ensure_owned_returns_the_owners_proposal() -> None:
    proposal = _proposal(owner_oid=OWNER_A)
    store = FakeProposalStore([proposal])

    found = asyncio.run(ensure_owned(store, proposal.id, OWNER_A))

    assert found == proposal


def test_story_1_8_ensure_owned_404s_the_same_for_unowned_or_missing() -> None:
    proposal = _proposal(owner_oid=OWNER_A)
    store = FakeProposalStore([proposal])

    with pytest.raises(ProposalNotFoundError):
        asyncio.run(ensure_owned(store, proposal.id, OWNER_B))
    with pytest.raises(ProposalNotFoundError):
        asyncio.run(ensure_owned(store, uuid4(), OWNER_A))


def test_story_1_8_display_name_zero_pads_the_owner_seq() -> None:
    assert display_name(_proposal(owner_seq=7)) == "Untitled_Proposal_007"


def test_story_1_8_display_name_uses_c1_and_c13_once_both_are_set() -> None:
    proposal = _proposal(answers=_answers(C1="Ally", C13="Macbeal"))

    assert display_name(proposal) == "Ally_Macbeal_Proposal_001"


def test_story_1_8_display_name_underscores_a_two_word_first_name() -> None:
    proposal = _proposal(owner_seq=8, answers=_answers(C1="Wei Ling", C13="Tan"))

    assert display_name(proposal) == "Wei_Ling_Tan_Proposal_008"


def test_story_1_8_display_name_trims_and_collapses_whitespace() -> None:
    proposal = _proposal(answers=_answers(C1="  Ally  ", C13=" Mac  Beal "))

    assert display_name(proposal) == "Ally_Mac_Beal_Proposal_001"


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param(_answers(C1="Ally"), id="first name only"),
        pytest.param(_answers(C13="Macbeal"), id="last name only"),
    ],
)
def test_story_1_8_display_name_stays_untitled_with_only_one_name(
    answers: dict[str, dict[str, object]],
) -> None:
    assert display_name(_proposal(answers=answers)) == "Untitled_Proposal_001"


def test_story_1_8_draft_view_has_the_ad5_shape_plus_display_name() -> None:
    # Never locked (Story 4.4): free, so "you" relative to any caller.
    view = draft_view(_proposal(lock_holder=None), SESSION_ID)

    assert view.keys() == {
        "id",
        "status",
        "schema_version",
        "revision",
        "lock",
        "active",
        "answers",
        "provenance",
        "quote",
        "display_name",
        "submitted_at",
    }
    assert view["status"] == "draft"
    assert view["revision"] == 0
    assert view["lock"] == {"holder": "you", "expires_at": None}
    assert view["quote"] is None
    assert view["answers"] == {}
    assert view["provenance"] == {}
    assert view["display_name"] == "Untitled_Proposal_001"
    assert view["submitted_at"] is None
    # FORM-222: the released (latest) schema's base active set with no answers is now v2's 37
    # (v1's 40 in test_visibility.py, minus N1/N2/N3 -- N4 was already inactive with no N3
    # answer, so dropping page 1 removes only those three from the base set).
    assert len(view["active"]) == 37


def test_story_1_8_draft_view_unwraps_answers_and_provenance() -> None:
    proposal = _proposal(answers=_answers(C1="Ally"))

    view = draft_view(proposal, SESSION_ID)

    assert view["answers"]["C1"] == "Ally"
    assert view["provenance"]["C1"] == {
        "source": "human",
        "updated_at": "2026-09-27T00:00:00Z",
    }


# Story 2.2 Part B: resolve_quote (the catalogue lookup) and quote_view (the wire shape).


class FakeCatalogue:
    """An in-memory ProductCatalogue (Story 2.1) that returns the given products."""

    def __init__(self, products: Sequence[Product]) -> None:
        self._products = products

    async def products(self) -> Sequence[Product]:
        return self._products


def _fsh() -> Product:
    # The Ally reference case (epic-2-context.md): FSH baseline 160, Maternity & newborn rider 30.
    return Product(
        code="FSH",
        name="FamilyShield Life & Health",
        type=ProductType.LIFE_HEALTH,
        covers_dependents=True,
        policy_terms=(PolicyTerm(code="20_yrs", label="20 yrs"),),
        sum_assured_min=Decimal("200000.00"),
        sum_assured_max=Decimal("600000.00"),
        default_sum_assured=Decimal("300000.00"),
        default_term="20_yrs",
        min_age=18,
        max_age=55,
        baseline_monthly=Decimal("160.00"),
        riders=(
            Rider(
                code="R07",
                name="Maternity & newborn",
                baseline_monthly=Decimal("30.00"),
            ),
        ),
    )


ALLY_DOB = "1994-11-20"
ALLY_CREATED = datetime(2026, 9, 25, 3, 0, tzinfo=UTC)


def test_story_2_2_resolve_quote_prices_ally_through_the_catalogue() -> None:
    proposal = _proposal(
        answers=_answers(P1="FSH", P2=["R07"], C2=ALLY_DOB), now=ALLY_CREATED
    )

    quote = asyncio.run(resolve_quote(proposal, FakeCatalogue([_fsh()])))

    assert quote is not None
    assert (quote.monthly, quote.yearly) == (Decimal("219.95"), Decimal("2507.42"))
    assert [line.item for line in quote.lines] == [
        "FamilyShield Life & Health",
        "Maternity & newborn",
    ]


def test_story_2_2_resolve_quote_is_none_without_p1_or_c2() -> None:
    without_p1 = _proposal(answers=_answers(C2=ALLY_DOB), now=ALLY_CREATED)
    without_c2 = _proposal(answers=_answers(P1="FSH"), now=ALLY_CREATED)
    catalogue = FakeCatalogue([_fsh()])

    assert asyncio.run(resolve_quote(without_p1, catalogue)) is None
    assert asyncio.run(resolve_quote(without_c2, catalogue)) is None


def test_story_2_2_resolve_quote_is_none_for_an_unknown_p1() -> None:
    proposal = _proposal(
        answers=_answers(P1="NOSUCHPRODUCT", C2=ALLY_DOB), now=ALLY_CREATED
    )

    assert asyncio.run(resolve_quote(proposal, FakeCatalogue([_fsh()]))) is None


def test_story_2_2_resolve_quote_is_none_for_a_rider_foreign_to_p1() -> None:
    # R01 belongs to LT20, not FSH.
    proposal = _proposal(
        answers=_answers(P1="FSH", P2=["R01"], C2=ALLY_DOB), now=ALLY_CREATED
    )

    assert asyncio.run(resolve_quote(proposal, FakeCatalogue([_fsh()]))) is None


def test_story_2_2_resolve_quote_with_no_riders_is_the_product_alone() -> None:
    proposal = _proposal(answers=_answers(P1="FSH", C2=ALLY_DOB), now=ALLY_CREATED)

    quote = asyncio.run(resolve_quote(proposal, FakeCatalogue([_fsh()])))

    assert quote is not None
    assert [line.item for line in quote.lines] == ["FamilyShield Life & Health"]


def test_story_2_2_draft_view_alone_leaves_quote_null() -> None:
    # draft_view is pure and takes no catalogue; resolve_quote is the caller's separate step.
    proposal = _proposal(
        answers=_answers(P1="FSH", P2=["R07"], C2=ALLY_DOB), now=ALLY_CREATED
    )

    assert draft_view(proposal, SESSION_ID)["quote"] is None


def test_story_2_2_quote_view_maps_the_quote_to_the_wire_shape() -> None:
    proposal = _proposal(
        answers=_answers(P1="FSH", P2=["R07"], C2=ALLY_DOB), now=ALLY_CREATED
    )
    quote = asyncio.run(resolve_quote(proposal, FakeCatalogue([_fsh()])))

    assert quote_view(quote) == {
        "monthly": Decimal("219.95"),
        "yearly": Decimal("2507.42"),
        "lines": [
            {
                "item": "FamilyShield Life & Health",
                "monthly": Decimal("185.22"),
                "yearly": Decimal("2111.51"),
            },
            {
                "item": "Maternity & newborn",
                "monthly": Decimal("34.73"),
                "yearly": Decimal("395.91"),
            },
        ],
    }


def test_story_2_2_quote_view_of_none_is_none() -> None:
    assert quote_view(None) is None


def test_story_2_2_resolve_quote_is_none_for_a_malformed_c2() -> None:
    # C2 is schema-validated as format: date on write, but a stored value could still predate that
    # check; a malformed date degrades to null like every other unpriceable case, never a 500.
    proposal = _proposal(answers=_answers(P1="FSH", C2="not-a-date"), now=ALLY_CREATED)

    assert asyncio.run(resolve_quote(proposal, FakeCatalogue([_fsh()]))) is None


# Story 1.10: apply_answers -- diff, revision, validation and the AD-15 post-write recompute.


def test_story_1_10_create_draft_applies_x_simple_defaults_at_revision_0() -> None:
    clock = FakeClock()

    proposal = asyncio.run(create_draft(FakeProposalStore(), OWNER_A, clock))

    assert proposal.revision == 0
    for question_id in ("Y3", "H7", "H8", "H9", "H10", "H11", "H12", "H13", "H14"):
        assert proposal.answers[question_id] == {
            "value": "No",
            "source": "default",
            "updated_at": "2026-09-26T09:00:00Z",
        }
    # G1 and H15 are x-simple too, but inactive with no C3 answer: never defaulted (FR34, FR35).
    assert "G1" not in proposal.answers
    assert "H15" not in proposal.answers


def test_story_1_10_apply_answers_happy_path_bumps_revision_and_stores_human_source() -> (
    None
):
    proposal = _proposal(schema_version=1)
    clock = FakeClock(datetime(2026, 9, 27, 1, 0, tzinfo=UTC))

    updated = apply_answers(SCHEMA, proposal, 0, {"C1": "Ally"}, clock, (), SESSION_ID)

    assert updated is not None
    assert updated.revision == 1
    assert updated.answers["C1"] == {
        "value": "Ally",
        "source": "human",
        "updated_at": "2026-09-27T01:00:00Z",
    }
    assert updated.updated_at == clock.now()


def test_story_1_10_apply_answers_leaves_an_unchanged_value_untouched() -> None:
    proposal = _proposal(schema_version=1, answers=_answers(C1="Ally"))
    clock = FakeClock(datetime(2026, 9, 27, 1, 0, tzinfo=UTC))

    updated = apply_answers(SCHEMA, proposal, 0, {"C1": "Ally"}, clock, (), SESSION_ID)

    assert updated is not None
    assert updated.revision == 1  # the transaction still completed
    assert (
        updated.answers["C1"]
        == {
            "value": "Ally",
            "source": "human",
            "updated_at": "2026-09-27T00:00:00Z",  # untouched: the same value the fixture already had
        }
    )


def test_story_1_10_apply_answers_stale_revision_returns_none_and_writes_nothing() -> (
    None
):
    proposal = _proposal(schema_version=1, answers=_answers(C1="Ally"))

    assert (
        apply_answers(SCHEMA, proposal, 5, {"C1": "Bob"}, FakeClock(), (), SESSION_ID)
        is None
    )


def test_story_1_10_apply_answers_rejects_d1_whatever_its_value() -> None:
    proposal = _proposal(schema_version=1)

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"D1": True}, FakeClock(), (), SESSION_ID)
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("D1", ErrorCode.INACTIVE_FIELD)


def test_story_1_10_apply_answers_rejects_an_unknown_field() -> None:
    proposal = _proposal(schema_version=1)

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"Z9": "x"}, FakeClock(), (), SESSION_ID)
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("Z9", ErrorCode.UNKNOWN_FIELD)


def test_story_1_10_apply_answers_rejects_an_inactive_field() -> None:
    proposal = _proposal(schema_version=1)  # no C3 answer yet: G1 is inactive

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"G1": "Yes"}, FakeClock(), (), SESSION_ID)
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("G1", ErrorCode.INACTIVE_FIELD)


def test_story_1_10_apply_answers_accepts_a_field_the_same_patch_activates() -> None:
    proposal = _proposal(schema_version=1)

    updated = apply_answers(
        SCHEMA, proposal, 0, {"C3": "female", "G1": "Yes"}, FakeClock(), (), SESSION_ID
    )

    assert updated is not None
    assert updated.answers["G1"]["value"] == "Yes"
    assert updated.answers["G1"]["source"] == "human"
    # H15 is x-simple and now active: the post-write recompute defaults it (FR1, FR34, FR35).
    assert updated.answers["H15"] == {
        "value": "No",
        "source": "default",
        "updated_at": updated.answers["H15"]["updated_at"],
    }
    # N8 is x-fill: ask, not x-simple: also now active, but never defaulted.
    assert "N8" not in updated.answers


def test_story_1_10_apply_answers_clears_a_text_answer_to_null() -> None:
    proposal = _proposal(
        schema_version=1, answers=_answers(N6="Yes", N7="a pack a day")
    )

    updated = apply_answers(
        SCHEMA, proposal, 0, {"N7": None}, FakeClock(), (), SESSION_ID
    )

    assert updated is not None
    assert updated.answers["N7"]["value"] is None
    assert updated.answers["N7"]["source"] == "human"


def test_story_1_10_apply_answers_rejects_null_on_a_choice_question() -> None:
    # FORM-222: N6 stands in for "any Yes/No choice question" here (N3 dropped from the released
    # schema with page 1); SCHEMA is the latest version, so the field under test must be one of
    # its own questions.
    proposal = _proposal(schema_version=1, answers=_answers(N6="Yes"))

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"N6": None}, FakeClock(), (), SESSION_ID)
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("N6", ErrorCode.INVALID_VALUE)


def test_story_1_10_apply_answers_rejects_h1_out_of_range() -> None:
    proposal = _proposal(schema_version=1)

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"H1": 500}, FakeClock(), (), SESSION_ID)
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("H1", ErrorCode.OUT_OF_RANGE)


def test_story_1_10_apply_answers_rejects_c7_invalid_format() -> None:
    proposal = _proposal(schema_version=1)

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"C7": "abc"}, FakeClock(), (), SESSION_ID)
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("C7", ErrorCode.INVALID_FORMAT)


def test_story_1_10_apply_answers_rejects_c2_age_out_of_range_with_a_worded_message() -> (
    None
):
    proposal = _proposal(schema_version=1)
    clock = FakeClock(datetime(2026, 9, 26, 9, 0, tzinfo=UTC))

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"C2": "2020-01-01"}, clock, (), SESSION_ID)
    [error] = excinfo.value.errors
    assert error.field == "C2"
    assert error.code is ErrorCode.OUT_OF_RANGE
    assert error.message == "Enter a date between 1956 and 2008"


def test_story_1_10_apply_answers_rejects_an_enum_mismatch() -> None:
    proposal = _proposal(schema_version=1)

    with pytest.raises(DomainError) as excinfo:
        apply_answers(
            SCHEMA, proposal, 0, {"C3": "unknown"}, FakeClock(), (), SESSION_ID
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("C3", ErrorCode.INVALID_VALUE)
    assert error.message == "Choose one of the listed options."


def test_story_1_10_apply_answers_rejects_an_empty_array_with_minitems() -> None:
    proposal = _proposal(schema_version=1)

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"H4": []}, FakeClock(), (), SESSION_ID)
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("H4", ErrorCode.INVALID_VALUE)
    assert error.message == "Choose at least one option."


def test_story_1_10_apply_answers_rejects_duplicate_array_items() -> None:
    proposal = _proposal(schema_version=1)

    with pytest.raises(DomainError) as excinfo:
        apply_answers(
            SCHEMA, proposal, 0, {"H4": ["none", "none"]}, FakeClock(), (), SESSION_ID
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("H4", ErrorCode.INVALID_VALUE)
    assert error.message == "Choose each option only once."


def test_story_1_10_apply_answers_removes_inactive_answers_on_recompute() -> None:
    proposal = _proposal(
        schema_version=1,
        answers=_answers(
            C3="female", G1="Yes", G2=["live_birth"], G3="2019", H15="No", N8="No"
        ),
    )

    updated = apply_answers(
        SCHEMA, proposal, 0, {"C3": "male"}, FakeClock(), (), SESSION_ID
    )

    assert updated is not None
    assert not {"G1", "G2", "G3", "H15", "N8"} & updated.answers.keys()


def test_story_1_10_apply_answers_never_overwrites_an_answer_already_there() -> None:
    proposal = _proposal(schema_version=1, answers=_answers(Y3="Yes"))

    updated = apply_answers(
        SCHEMA, proposal, 0, {"C1": "Ally"}, FakeClock(), (), SESSION_ID
    )

    assert updated is not None
    assert updated.answers["Y3"] == {
        "value": "Yes",
        "source": "human",
        "updated_at": "2026-09-27T00:00:00Z",
    }


def test_story_1_10_fake_store_update_answers_mirrors_the_sql_adapters_semantics() -> (
    None
):
    store = FakeProposalStore()
    clock = FakeClock()
    proposal = asyncio.run(create_draft(store, OWNER_A, clock))

    def apply(current: Proposal) -> Proposal | None:
        return apply_answers(
            SCHEMA, current, proposal.revision, {"C1": "Ally"}, clock, (), SESSION_ID
        )

    updated = asyncio.run(store.update_answers(proposal.id, proposal.revision, apply))
    assert updated is not None
    assert updated.answers["C1"]["value"] == "Ally"

    stale = asyncio.run(store.update_answers(proposal.id, proposal.revision, apply))
    assert stale is None  # the fixture's own revision moved on after the first write

    missing = asyncio.run(store.update_answers(uuid4(), 0, apply))
    assert missing is None


# Story 2.3: apply_answers's P1/P2/P3/N5 product checks (epic-2-context.md "Selection rules").


def _elh() -> Product:
    # Essentials Life & Health: no riders, two terms, sum assured 100000-300000.
    return Product(
        code="ELH",
        name="Essentials Life & Health",
        type=ProductType.LIFE_HEALTH,
        covers_dependents=False,
        policy_terms=(
            PolicyTerm(code="10_yrs", label="10 yrs"),
            PolicyTerm(code="20_yrs", label="20 yrs"),
        ),
        sum_assured_min=Decimal("100000.00"),
        sum_assured_max=Decimal("300000.00"),
        default_sum_assured=Decimal("150000.00"),
        default_term="10_yrs",
        min_age=18,
        max_age=60,
        baseline_monthly=Decimal("100.00"),
        riders=(),
    )


def _cfh() -> Product:
    # CareFirst Health: no sum assured at all.
    return Product(
        code="CFH",
        name="CareFirst Health",
        type=ProductType.HEALTH,
        covers_dependents=True,
        policy_terms=(PolicyTerm(code="1_yr_renewable", label="1 yr, renewable"),),
        sum_assured_min=None,
        sum_assured_max=None,
        default_sum_assured=None,
        default_term="1_yr_renewable",
        min_age=18,
        max_age=65,
        baseline_monthly=Decimal("45.00"),
        riders=(),
    )


PRODUCTS_2_3 = (_fsh(), _elh(), _cfh())

# The default FakeClock() reads 2026-09-26T09:00 UTC == 2026-09-26T17:00 MYT: ages computed from
# it below use that Malaysian calendar date.
AGE_31_DOB = "1994-11-20"  # the Ally reference case: 31 on the default clock.
AGE_58_DOB = "1968-01-01"  # 58 on the default clock -- past FSH's 18-55 range.


def test_story_2_3_p1_in_range_is_accepted() -> None:
    proposal = _proposal(schema_version=1, answers=_answers(C2=AGE_31_DOB))

    updated = apply_answers(
        SCHEMA, proposal, 0, {"P1": "FSH"}, FakeClock(), PRODUCTS_2_3, SESSION_ID
    )

    assert updated is not None
    assert updated.answers["P1"]["value"] == "FSH"


def test_form_18_p1_outside_the_product_age_range_is_accepted() -> None:
    """Owner decision (owner, 2026-09-27): P1 is no longer checked against the product's age range."""
    proposal = _proposal(schema_version=1, answers=_answers(C2=AGE_58_DOB))

    updated = apply_answers(
        SCHEMA, proposal, 0, {"P1": "FSH"}, FakeClock(), PRODUCTS_2_3, SESSION_ID
    )

    assert updated.answers["P1"]["value"] == "FSH"


def test_p1_age_is_measured_at_created_at_not_the_clock() -> None:
    # 55 when the draft was created (2026-09-27), 56 by the clock: FSH (18-55) still fits, the same
    # answer pricing and validate_proposal give.
    created = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _proposal(
        schema_version=1,
        answers=_answers(C2="1970-10-10"),
        now=created,
        lock_expires_at=datetime(2026, 12, 31, tzinfo=UTC),
    )
    later = FakeClock(datetime(2026, 11, 1, 9, 0, tzinfo=UTC))

    updated = apply_answers(
        SCHEMA, proposal, 0, {"P1": "FSH"}, later, PRODUCTS_2_3, SESSION_ID
    )

    assert updated is not None
    assert updated.answers["P1"]["value"] == "FSH"


def test_story_2_3_p1_unknown_code_is_invalid_value() -> None:
    proposal = _proposal(schema_version=1, answers=_answers(C2=AGE_31_DOB))

    with pytest.raises(DomainError) as excinfo:
        apply_answers(
            SCHEMA, proposal, 0, {"P1": "XYZ"}, FakeClock(), PRODUCTS_2_3, SESSION_ID
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("P1", ErrorCode.INVALID_VALUE)


def test_story_2_3_p1_with_no_dob_yet_only_runs_the_exists_check() -> None:
    proposal = _proposal(schema_version=1)  # no C2 at all

    updated = apply_answers(
        SCHEMA, proposal, 0, {"P1": "FSH"}, FakeClock(), PRODUCTS_2_3, SESSION_ID
    )

    assert updated is not None
    assert updated.answers["P1"]["value"] == "FSH"


def test_story_2_3_p2_rider_foreign_to_p1_is_invalid_value() -> None:
    proposal = _proposal(schema_version=1, answers=_answers(P1="ELH"))

    with pytest.raises(DomainError) as excinfo:
        apply_answers(
            SCHEMA, proposal, 0, {"P2": ["R07"]}, FakeClock(), PRODUCTS_2_3, SESSION_ID
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("P2", ErrorCode.INVALID_VALUE)


def test_story_2_3_p3_not_one_of_p1s_terms_is_invalid_value() -> None:
    proposal = _proposal(schema_version=1, answers=_answers(P1="ELH"))

    with pytest.raises(DomainError) as excinfo:
        apply_answers(
            SCHEMA, proposal, 0, {"P3": "30_yrs"}, FakeClock(), PRODUCTS_2_3, SESSION_ID
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("P3", ErrorCode.INVALID_VALUE)


def test_story_2_3_n5_out_of_range_for_p1s_sum_assured() -> None:
    proposal = _proposal(schema_version=1, answers=_answers(P1="ELH"))

    with pytest.raises(DomainError) as excinfo:
        apply_answers(
            SCHEMA, proposal, 0, {"N5": 500000}, FakeClock(), PRODUCTS_2_3, SESSION_ID
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("N5", ErrorCode.OUT_OF_RANGE)


def test_story_2_3_n5_on_a_no_sum_assured_product_is_invalid_value() -> None:
    proposal = _proposal(schema_version=1, answers=_answers(P1="CFH"))

    with pytest.raises(DomainError) as excinfo:
        apply_answers(
            SCHEMA, proposal, 0, {"N5": 50000}, FakeClock(), PRODUCTS_2_3, SESSION_ID
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("N5", ErrorCode.INVALID_VALUE)


def test_story_2_3_p3_and_n5_run_no_product_check_while_p1_is_unset() -> None:
    proposal = _proposal(schema_version=1)  # P1 never set

    updated = apply_answers(
        SCHEMA,
        proposal,
        0,
        {"P3": "anything", "N5": 1},
        FakeClock(),
        PRODUCTS_2_3,
        SESSION_ID,
    )

    assert updated is not None
    assert updated.answers["P3"]["value"] == "anything"
    assert updated.answers["N5"]["value"] == 1


def test_story_2_3_a_c2_write_is_accepted_even_though_it_invalidates_stored_p1() -> (
    None
):
    # P1=FSH (18-55) already stored; the PATCH only touches C2, ageing the insured to 58.
    proposal = _proposal(schema_version=1, answers=_answers(P1="FSH", C2="1994-11-20"))

    updated = apply_answers(
        SCHEMA, proposal, 0, {"C2": AGE_58_DOB}, FakeClock(), PRODUCTS_2_3, SESSION_ID
    )

    assert updated is not None
    assert updated.answers["C2"]["value"] == AGE_58_DOB
    assert (
        updated.answers["P1"]["value"] == "FSH"
    )  # kept unchanged; 3.1's job to flag it


def test_story_2_3_a_p1_write_is_accepted_even_though_it_invalidates_stored_p2_p3_n5() -> (
    None
):
    # FSH's own P2/P3/N5 stored; the PATCH only touches P1, to a product with none of them.
    proposal = _proposal(
        schema_version=1,
        answers=_answers(P1="FSH", P2=["R07"], P3="20_yrs", N5=300000),
    )

    updated = apply_answers(
        SCHEMA, proposal, 0, {"P1": "CFH"}, FakeClock(), PRODUCTS_2_3, SESSION_ID
    )

    assert updated is not None
    assert updated.answers["P1"]["value"] == "CFH"
    assert updated.answers["P2"]["value"] == [
        "R07"
    ]  # kept unchanged; 3.1's job to flag it
    assert updated.answers["P3"]["value"] == "20_yrs"
    assert updated.answers["N5"]["value"] == 300000


def test_story_2_3_p1_p2_change_in_the_same_patch_checks_p2_against_the_new_p1() -> (
    None
):
    # A same-PATCH P1 change is what a same-PATCH P2 is checked against (spec Design "Always").
    proposal = _proposal(schema_version=1, answers=_answers(P1="FSH", P2=["R07"]))

    updated = apply_answers(
        SCHEMA,
        proposal,
        0,
        {"P1": "FSH", "P2": ["R07"]},
        FakeClock(),
        PRODUCTS_2_3,
        SESSION_ID,
    )
    assert updated is not None
    assert updated.answers["P2"]["value"] == ["R07"]

    with pytest.raises(DomainError) as excinfo:
        apply_answers(
            SCHEMA,
            proposal,
            0,
            {"P1": "ELH", "P2": ["R07"]},
            FakeClock(),
            PRODUCTS_2_3,
            SESSION_ID,
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("P2", ErrorCode.INVALID_VALUE)


# Story 3.1: validate_proposal -- the read-only whole-proposal check behind
# POST /api/proposals/:id/validate (AD-7, AD-12, AD-15).

# Every active question on the released (latest) schema, answered validly, with C3 = male and
# N6 = No so the gynaecology/smoking follow-ups (HIDDEN_WITHOUT_ANSWERS in test_visibility.py,
# minus N4/N3 -- FORM-222 dropped page 1) stay inactive -- the released schema's own 37 "BASE"
# ids (test_proposals.py's own `test_story_1_8_draft_view_has_the_ad5_shape_plus_display_name`),
# minus the always-optional C12/N5/P2, which are included here anyway to keep the fixture
# "everything answered" (spec's "clean draft" scenario). `_complete_proposal` pins no explicit
# schema_version, so it always matches `SCHEMA` (`load_schema(latest_version())`) above.
COMPLETE_ANSWERS: dict[str, object] = {
    "N5": 300000,
    "N6": "No",
    "P1": "FSH",
    "P2": ["R07"],
    "P3": "20_yrs",
    "Y1": "monthly",
    "Y2": "credit_card",
    "Y3": "No",
    "C1": "Ally",
    "C2": ALLY_DOB,
    "C3": "male",
    "C4": "MY",
    "C5": "MY",
    "C6": "S1234567",
    "C7": "ally@example.test",
    "C8": "+60123456789",
    "C9": "Graphic designer",
    "C10": "1 Jalan Test",
    "C11": "single",
    "C12": "30k_60k",
    "C13": "Macbeal",
    "C14": "Kuala Lumpur",
    "C15": "50450",
    "H1": 165,
    "H2": 58,
    "H3": "none",
    "H4": ["none"],
    "H5": ["none"],
    "H6": "No",
    "H7": "No",
    "H8": "No",
    "H9": "No",
    "H10": "No",
    "H11": "No",
    "H12": "No",
    "H13": "No",
    "H14": "No",
}


def _complete_proposal(
    overrides: dict[str, object] | None = None,
    *,
    omit: tuple[str, ...] = (),
    now: datetime = ALLY_CREATED,
) -> Proposal:
    values = {**COMPLETE_ANSWERS, **(overrides or {})}
    for question_id in omit:
        values.pop(question_id, None)
    # No explicit schema_version: this fixture must always match SCHEMA (the latest version)
    # above, since every test here validates it against SCHEMA.
    return _proposal(answers=_answers(**values), now=now)


def test_story_3_1_validate_proposal_is_clean_for_a_complete_valid_draft() -> None:
    proposal = _complete_proposal()

    errors = asyncio.run(validate_proposal(SCHEMA, proposal, FakeCatalogue([_fsh()])))

    assert errors == []


def test_story_3_1_validate_proposal_reports_exactly_three_errors() -> None:
    # The AC's own scenario: an impossible DOB, an unknown product, and a missing required field.
    proposal = _complete_proposal({"C2": "1994-02-30", "P1": "XYZ"}, omit=("H1",))

    errors = asyncio.run(validate_proposal(SCHEMA, proposal, FakeCatalogue([_fsh()])))

    assert {(error.field, error.code) for error in errors} == {
        ("C2", ErrorCode.INVALID_FORMAT),
        ("P1", ErrorCode.INVALID_VALUE),
        ("H1", ErrorCode.REQUIRED),
    }
    assert len(errors) == 3
    [h1_error] = [error for error in errors if error.field == "H1"]
    assert h1_error.message == "Answer required"


@pytest.mark.parametrize(
    "dob",
    [
        pytest.param("2008-09-26", id="17 at created_at"),
        pytest.param("1955-09-25", id="71 at created_at"),
    ],
)
def test_story_3_1_validate_proposal_rejects_c2_outside_the_age_range_at_created_at(
    dob: str,
) -> None:
    # A product with a much wider age range than FSH's 18-55, so this exercises only C2's own
    # x-age-range check (18-70), not also P1's product-age rule.
    wide_range_product = replace(_fsh(), min_age=0, max_age=130)
    proposal = _complete_proposal({"C2": dob})

    errors = asyncio.run(
        validate_proposal(SCHEMA, proposal, FakeCatalogue([wide_range_product]))
    )

    assert [(error.field, error.code) for error in errors] == [
        ("C2", ErrorCode.OUT_OF_RANGE)
    ]


def test_story_3_1_validate_proposal_measures_c2_age_at_created_at_not_a_later_now() -> (
    None
):
    # 17 at ALLY_CREATED (2026-09-25), 18 a year later: same C2, only proposal.created_at differs.
    # validate_proposal takes no clock and no "now" argument at all, so this is the only way this
    # check could ever move (AD-7).
    wide_range_product = replace(_fsh(), min_age=0, max_age=130)
    dob = "2008-09-26"
    younger = _complete_proposal({"C2": dob}, now=ALLY_CREATED)
    older = _complete_proposal({"C2": dob}, now=ALLY_CREATED.replace(year=2027))

    younger_errors = asyncio.run(
        validate_proposal(SCHEMA, younger, FakeCatalogue([wide_range_product]))
    )
    older_errors = asyncio.run(
        validate_proposal(SCHEMA, older, FakeCatalogue([wide_range_product]))
    )

    assert any(error.field == "C2" for error in younger_errors)
    assert not any(error.field == "C2" for error in older_errors)


def test_story_3_1_validate_proposal_reports_product_rider_term_and_sum_assured_rules() -> (
    None
):
    proposal = _complete_proposal(
        {
            "C2": "1966-09-20",  # age 60: outside FSH's 18-55 range, allowed since FORM-18
            "P2": [
                "R01"
            ],  # belongs to no product in this catalogue (only FSH is seeded)
            "P3": "99_yrs",  # not one of FSH's policy terms
            "N5": 700000,  # over FSH's 600000 sum-assured maximum
        }
    )

    errors = asyncio.run(validate_proposal(SCHEMA, proposal, FakeCatalogue([_fsh()])))

    assert {(error.field, error.code) for error in errors} == {
        ("P2", ErrorCode.INVALID_VALUE),
        ("P3", ErrorCode.INVALID_VALUE),
        ("N5", ErrorCode.OUT_OF_RANGE),
    }


def test_story_3_1_validate_proposal_unknown_product_skips_its_dependent_rules() -> (
    None
):
    # Design Notes "Product rules order": once P1 fails to resolve, nothing checks P2/P3/N5
    # against a product -- there is nothing to check them against -- so only P1 gets an error.
    proposal = _complete_proposal(
        {"P1": "XYZ", "P2": ["ANY"], "P3": "any_term", "N5": 999}
    )

    errors = asyncio.run(validate_proposal(SCHEMA, proposal, FakeCatalogue([_fsh()])))

    assert [(error.field, error.code) for error in errors] == [
        ("P1", ErrorCode.INVALID_VALUE)
    ]


def test_story_3_1_validate_proposal_never_reports_inactive_questions_or_d1() -> None:
    # C3 = male leaves G1 (and G2/G3/N8/H15) inactive; a stale/invalid G1 answer must never be
    # reported. D1 is x-fill: human, never active, whatever it holds.
    proposal = _complete_proposal({"G1": "not-a-valid-answer", "D1": "not-a-boolean"})

    errors = asyncio.run(validate_proposal(SCHEMA, proposal, FakeCatalogue([_fsh()])))

    assert errors == []


def test_story_3_1_validate_proposal_never_mutates_the_proposal() -> None:
    proposal = _complete_proposal({"P1": "XYZ"})
    before = proposal

    asyncio.run(validate_proposal(SCHEMA, proposal, FakeCatalogue([_fsh()])))

    assert proposal == before


# Story 4.4: the edit lock (relative_holder, lock_view, acquire_lock; apply_answers's lock check).


@pytest.mark.parametrize(
    ("holder", "expected"),
    [
        pytest.param(None, "you", id="free"),
        pytest.param(SESSION_ID, "you", id="held by the caller"),
        pytest.param("ai", "ai", id="held by the ai"),
        pytest.param(OTHER_SESSION_ID, "other_session", id="held by another session"),
    ],
)
def test_story_4_4_relative_holder(holder: str | None, expected: str) -> None:
    assert relative_holder(holder, SESSION_ID) == expected


def test_story_4_4_lock_view_maps_the_proposal_to_the_ad5_shape() -> None:
    expires = datetime(2026, 9, 27, 9, 1, tzinfo=UTC)
    proposal = _proposal(lock_holder=SESSION_ID, lock_expires_at=expires)

    assert lock_view(proposal, SESSION_ID) == {
        "holder": "you",
        "expires_at": "2026-09-27T09:01:00Z",
    }


def test_story_4_4_lock_view_of_a_free_lock_has_a_null_expiry() -> None:
    proposal = _proposal(lock_holder=None)

    assert lock_view(proposal, SESSION_ID) == {"holder": "you", "expires_at": None}


def test_story_4_4_acquire_on_open_with_no_live_lock() -> None:
    proposal = _proposal(lock_holder=None)
    store = FakeProposalStore([proposal])
    clock = FakeClock(datetime(2026, 9, 27, 9, 0, tzinfo=UTC))

    lock = asyncio.run(
        acquire_lock(store, proposal.id, OWNER_A, SESSION_ID, False, clock)
    )

    assert lock == {"holder": "you", "expires_at": "2026-09-27T09:01:00Z"}
    stored = asyncio.run(store.get(proposal.id))
    assert stored is not None
    assert stored.lock_holder == SESSION_ID
    assert stored.lock_expires_at == clock.now() + LOCK_DURATION


def test_story_4_4_renew_extends_the_expiry_for_the_current_holder() -> None:
    clock = FakeClock(datetime(2026, 9, 27, 9, 0, tzinfo=UTC))
    proposal = _proposal(
        lock_holder=SESSION_ID, lock_expires_at=clock.now() + timedelta(seconds=30)
    )
    store = FakeProposalStore([proposal])

    clock.advance(timedelta(seconds=20))  # still live: 10s left on the old expiry
    lock = asyncio.run(
        acquire_lock(store, proposal.id, OWNER_A, SESSION_ID, False, clock)
    )

    assert lock == {"holder": "you", "expires_at": "2026-09-27T09:01:20Z"}


def test_story_4_4_blocked_by_another_live_session_without_take_over() -> None:
    clock = FakeClock(datetime(2026, 9, 27, 9, 0, tzinfo=UTC))
    proposal = _proposal(
        lock_holder=OTHER_SESSION_ID,
        lock_expires_at=clock.now() + timedelta(seconds=30),
    )
    store = FakeProposalStore([proposal])

    lock = asyncio.run(
        acquire_lock(store, proposal.id, OWNER_A, SESSION_ID, False, clock)
    )

    assert lock == {"holder": "other_session", "expires_at": "2026-09-27T09:00:30Z"}
    stored = asyncio.run(store.get(proposal.id))
    assert stored is not None
    assert stored.lock_holder == OTHER_SESSION_ID  # unchanged


def test_story_4_4_take_over_moves_the_lock_from_another_live_session() -> None:
    clock = FakeClock(datetime(2026, 9, 27, 9, 0, tzinfo=UTC))
    proposal = _proposal(
        lock_holder=OTHER_SESSION_ID,
        lock_expires_at=clock.now() + timedelta(seconds=30),
    )
    store = FakeProposalStore([proposal])

    lock = asyncio.run(
        acquire_lock(store, proposal.id, OWNER_A, SESSION_ID, True, clock)
    )

    assert lock == {"holder": "you", "expires_at": "2026-09-27T09:01:00Z"}
    # The session that lost it now sees itself as "other_session" (spec matrix).
    stored = asyncio.run(store.get(proposal.id))
    assert stored is not None
    assert relative_holder(stored.lock_holder, OTHER_SESSION_ID) == "other_session"


def test_story_4_4_ai_refuses_a_take_over() -> None:
    clock = FakeClock(datetime(2026, 9, 27, 9, 0, tzinfo=UTC))
    proposal = _proposal(
        lock_holder="ai", lock_expires_at=clock.now() + timedelta(minutes=5)
    )
    store = FakeProposalStore([proposal])

    lock = asyncio.run(
        acquire_lock(store, proposal.id, OWNER_A, SESSION_ID, True, clock)
    )

    assert lock["holder"] == "ai"
    stored = asyncio.run(store.get(proposal.id))
    assert stored is not None
    assert stored.lock_holder == "ai"  # unchanged


def test_story_4_4_an_expired_lock_is_treated_as_free() -> None:
    clock = FakeClock(datetime(2026, 9, 27, 9, 0, tzinfo=UTC))
    proposal = _proposal(
        lock_holder=OTHER_SESSION_ID,
        lock_expires_at=clock.now() - timedelta(seconds=1),  # expired a second ago
    )
    store = FakeProposalStore([proposal])

    lock = asyncio.run(
        acquire_lock(store, proposal.id, OWNER_A, SESSION_ID, False, clock)
    )

    assert lock == {"holder": "you", "expires_at": "2026-09-27T09:01:00Z"}


def test_story_4_4_acquire_lock_404s_the_same_for_unowned_or_missing() -> None:
    proposal = _proposal(owner_oid=OWNER_A, lock_holder=None)
    store = FakeProposalStore([proposal])
    clock = FakeClock()

    with pytest.raises(ProposalNotFoundError):
        asyncio.run(acquire_lock(store, proposal.id, OWNER_B, SESSION_ID, False, clock))
    with pytest.raises(ProposalNotFoundError):
        asyncio.run(acquire_lock(store, uuid4(), OWNER_A, SESSION_ID, False, clock))


def test_story_4_4_apply_answers_rejects_a_write_from_a_session_that_isnt_the_holder() -> (
    None
):
    proposal = _proposal(schema_version=1, lock_holder=OTHER_SESSION_ID)

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"C1": "Ally"}, FakeClock(), (), SESSION_ID)
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("lock", ErrorCode.LOCK_NOT_HELD)


def test_story_4_4_apply_answers_rejects_a_write_once_the_callers_own_lock_expired() -> (
    None
):
    clock = FakeClock(datetime(2026, 9, 27, 9, 0, tzinfo=UTC))
    proposal = _proposal(
        schema_version=1,
        lock_holder=SESSION_ID,
        lock_expires_at=clock.now() - timedelta(seconds=1),
    )

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"C1": "Ally"}, clock, (), SESSION_ID)
    [error] = excinfo.value.errors
    assert error.code == ErrorCode.LOCK_NOT_HELD


def test_story_4_4_apply_answers_writes_nothing_when_the_lock_isnt_held() -> None:
    proposal = _proposal(
        schema_version=1, answers=_answers(C1="Ally"), lock_holder=OTHER_SESSION_ID
    )

    with pytest.raises(DomainError):
        apply_answers(SCHEMA, proposal, 0, {"C1": "Bob"}, FakeClock(), (), SESSION_ID)
    # apply_answers raised before touching anything: the same "raises, writes nothing" contract
    # as any other field error (AD-12) -- the original fixture is untouched either way, since it's
    # frozen, but this pins the intent.
    assert proposal.answers["C1"]["value"] == "Ally"


def test_story_4_4_apply_answers_still_returns_none_for_a_stale_revision_before_the_lock_check() -> (
    None
):
    # A stale expected_revision returns None with no exception, whatever the lock says (spec
    # Intent: the revision guard runs first).
    proposal = _proposal(schema_version=1, lock_holder=OTHER_SESSION_ID)

    assert (
        apply_answers(SCHEMA, proposal, 5, {"C1": "Ally"}, FakeClock(), (), SESSION_ID)
        is None
    )


# --- Story 4.3: turn_bound, apply_agent_patch, begin_turn/end_turn (spine AD-3, AD-4, AD-6,
# AD-14, AD-15) -----------------------------------------------------------------------------

_AI_TID = uuid4()


def _claims(tid: UUID = _AI_TID) -> TurnTokenClaims:
    return TurnTokenClaims(
        sub=OWNER_A, pid=uuid4(), tid=tid, exp=datetime(2026, 9, 27, 9, 30, tzinfo=UTC)
    )


def _ai_proposal(
    *,
    answers: dict[str, dict[str, object]] | None = None,
    status: ProposalStatus = ProposalStatus.DRAFT,
    tid: UUID | None = _AI_TID,
    lock_holder: str | None = "ai",
    lock_expires_at: datetime | None = None,
    now: datetime | None = None,
) -> Proposal:
    at = now or datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    return _proposal(
        answers=answers,
        status=status,
        now=at,
        lock_holder=lock_holder,
        lock_expires_at=(
            lock_expires_at
            if lock_expires_at is not None
            else at + timedelta(minutes=1)
        ),
        current_turn_id=tid,
    )


def test_story_4_3_turn_bound_true_when_ai_holds_the_lock_live_with_this_tid() -> None:
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _ai_proposal(now=now)

    assert turn_bound(proposal, _claims(), now) is True


def test_story_4_3_turn_bound_false_when_the_lock_isnt_held_by_ai() -> None:
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _ai_proposal(now=now, lock_holder=SESSION_ID)

    assert turn_bound(proposal, _claims(), now) is False


def test_story_4_3_turn_bound_false_once_the_lock_has_expired() -> None:
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _ai_proposal(now=now, lock_expires_at=now - timedelta(seconds=1))

    assert turn_bound(proposal, _claims(), now) is False


def test_story_4_3_turn_bound_false_for_a_stale_tid() -> None:
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _ai_proposal(now=now, tid=uuid4())

    assert turn_bound(proposal, _claims(tid=uuid4()), now) is False


def test_story_4_3_apply_agent_patch_rejects_when_not_turn_bound() -> None:
    proposal = _ai_proposal(lock_holder=SESSION_ID)

    with pytest.raises(DomainError) as excinfo:
        apply_agent_patch(SCHEMA, proposal, {"C1": "Ally"}, FakeClock(), (), _claims())
    [error] = excinfo.value.errors
    assert error.code == ErrorCode.LOCK_NOT_HELD


def test_story_4_3_apply_agent_patch_rejects_a_submitted_proposal() -> None:
    proposal = _ai_proposal(status=ProposalStatus.SUBMITTED)

    with pytest.raises(DomainError) as excinfo:
        apply_agent_patch(SCHEMA, proposal, {"C1": "Ally"}, FakeClock(), (), _claims())
    [error] = excinfo.value.errors
    assert error.code == ErrorCode.PROPOSAL_SUBMITTED


def test_story_4_3_apply_agent_patch_partially_applies_a_mixed_patch() -> None:
    proposal = _ai_proposal()

    updated, applied, errors = apply_agent_patch(
        SCHEMA, proposal, {"C1": "Ally", "Z9": "nope"}, FakeClock(), (), _claims()
    )

    assert applied == ["C1"]
    assert [error.field for error in errors] == ["Z9"]
    assert updated.answers["C1"] == {
        "value": "Ally",
        "source": "ai",
        "updated_at": "2026-09-26T09:00:00Z",
    }
    assert updated.revision == proposal.revision + 1


def test_story_4_3_apply_agent_patch_human_locked_wins_over_a_new_ai_value() -> None:
    proposal = _ai_proposal(answers=_answers(C1="Alice"))

    updated, applied, errors = apply_agent_patch(
        SCHEMA, proposal, {"C1": "Bob"}, FakeClock(), (), _claims()
    )

    assert applied == []
    assert [(error.field, error.code) for error in errors] == [
        ("C1", ErrorCode.HUMAN_LOCKED)
    ]
    assert updated.answers["C1"]["value"] == "Alice"  # unchanged


def test_story_4_3_apply_agent_patch_rejects_d1_as_not_agent_writable() -> None:
    proposal = _ai_proposal()

    updated, applied, errors = apply_agent_patch(
        SCHEMA, proposal, {"D1": True}, FakeClock(), (), _claims()
    )

    assert applied == []
    assert [(error.field, error.code) for error in errors] == [
        ("D1", ErrorCode.NOT_AGENT_WRITABLE)
    ]
    assert "D1" not in updated.answers


def test_story_4_3_apply_agent_patch_rejects_an_unknown_field() -> None:
    proposal = _ai_proposal()

    _updated, applied, errors = apply_agent_patch(
        SCHEMA, proposal, {"Z9": "x"}, FakeClock(), (), _claims()
    )

    assert applied == []
    assert [(error.field, error.code) for error in errors] == [
        ("Z9", ErrorCode.UNKNOWN_FIELD)
    ]


def test_story_4_3_apply_agent_patch_rejects_an_inactive_field() -> None:
    proposal = _ai_proposal()  # no C3 answer yet: G1 is inactive

    _updated, applied, errors = apply_agent_patch(
        SCHEMA, proposal, {"G1": "Yes"}, FakeClock(), (), _claims()
    )

    assert applied == []
    assert [(error.field, error.code) for error in errors] == [
        ("G1", ErrorCode.INACTIVE_FIELD)
    ]


def test_story_4_3_apply_agent_patch_accepts_a_field_the_same_patch_activates() -> None:
    proposal = _ai_proposal()

    updated, applied, errors = apply_agent_patch(
        SCHEMA, proposal, {"C3": "female", "G1": "Yes"}, FakeClock(), (), _claims()
    )

    assert set(applied) == {"C3", "G1"}
    assert errors == []
    assert updated.answers["G1"]["value"] == "Yes"
    assert updated.answers["G1"]["source"] == "ai"


def test_story_4_3_apply_agent_patch_ignores_a_source_key_in_the_input() -> None:
    proposal = _ai_proposal()

    updated, applied, errors = apply_agent_patch(
        SCHEMA, proposal, {"C1": "Ally", "source": "human"}, FakeClock(), (), _claims()
    )

    assert applied == ["C1"]
    assert [(error.field, error.code) for error in errors] == [
        ("source", ErrorCode.UNKNOWN_FIELD)
    ]
    assert (
        updated.answers["C1"]["source"] == "ai"
    )  # never "human", whatever the caller sent


def test_story_4_3_apply_agent_patch_bumps_revision_even_with_no_applied_field() -> (
    None
):
    proposal = _ai_proposal()

    updated, applied, _errors = apply_agent_patch(
        SCHEMA, proposal, {"Z9": "x"}, FakeClock(), (), _claims()
    )

    assert applied == []
    assert updated.revision == proposal.revision + 1


def test_story_4_3_apply_agent_patch_a_no_op_write_keeps_the_stored_source() -> None:
    proposal = _ai_proposal(
        answers={
            "C1": {
                "value": "Ally",
                "source": "ai",
                "updated_at": "2026-09-01T00:00:00Z",
            }
        }
    )

    updated, applied, _errors = apply_agent_patch(
        SCHEMA, proposal, {"C1": "Ally"}, FakeClock(), (), _claims()
    )

    assert applied == ["C1"]
    assert updated.answers["C1"] == {
        "value": "Ally",
        "source": "ai",
        "updated_at": "2026-09-01T00:00:00Z",
    }


# --- FORM-219: apply_agent_patch maps an x-labels label to its code (spine AD-3) -----------


@pytest.mark.parametrize("value", ["Malaysia", "malaysia", "MALAYSIA", "MY"])
def test_form_219_apply_agent_patch_maps_a_country_label_to_its_code(
    value: str,
) -> None:
    proposal = _ai_proposal()

    updated, applied, errors = apply_agent_patch(
        SCHEMA, proposal, {"C4": value}, FakeClock(), (), _claims()
    )

    assert applied == ["C4"]
    assert errors == []
    assert updated.answers["C4"]["value"] == "MY"


def test_form_219_apply_agent_patch_maps_labels_on_every_x_labels_question() -> None:
    """Not just the countries the live incident was about: any enum question with ``x-labels``
    (here C3's sex-at-birth and C11's marital status) gets the same mapping."""
    proposal = _ai_proposal()

    updated, applied, errors = apply_agent_patch(
        SCHEMA,
        proposal,
        {"C3": "Male", "C11": "Married"},
        FakeClock(),
        (),
        _claims(),
    )

    assert set(applied) == {"C3", "C11"}
    assert errors == []
    assert updated.answers["C3"]["value"] == "male"
    assert updated.answers["C11"]["value"] == "married"


def test_form_219_apply_agent_patch_still_rejects_an_unmapped_label() -> None:
    proposal = _ai_proposal()

    _updated, applied, errors = apply_agent_patch(
        SCHEMA, proposal, {"C4": "Nowhereland"}, FakeClock(), (), _claims()
    )

    assert applied == []
    assert [(error.field, error.code) for error in errors] == [
        ("C4", ErrorCode.INVALID_VALUE)
    ]


def test_form_219_apply_agent_patch_leaves_non_string_values_alone() -> None:
    """A question with x-labels but a non-string incoming value (``None``, a clear attempt on a
    choice-shaped question) is never passed to the label lookup, so it fails the usual
    null-on-choice check rather than crashing or matching some label by accident."""
    proposal = _ai_proposal()

    _updated, applied, errors = apply_agent_patch(
        SCHEMA, proposal, {"C3": None}, FakeClock(), (), _claims()
    )

    assert applied == []
    assert [(error.field, error.code) for error in errors] == [
        ("C3", ErrorCode.INVALID_VALUE)
    ]


def test_story_4_3_begin_turn_binds_the_proposal_to_a_fresh_ai_turn() -> None:
    proposal = _proposal(owner_oid=OWNER_A, lock_holder=None, lock_expires_at=None)
    store = FakeProposalStore([proposal])
    clock = FakeClock()

    updated = asyncio.run(begin_turn(store, proposal.id, clock))

    assert updated is not None
    assert updated.lock_holder == "ai"
    assert updated.lock_expires_at == clock.now() + LOCK_DURATION
    assert updated.current_turn_id is not None


def test_story_4_3_end_turn_clears_the_lock_and_turn() -> None:
    proposal = _proposal(owner_oid=OWNER_A, lock_holder="ai", current_turn_id=uuid4())
    store = FakeProposalStore([proposal])

    updated = asyncio.run(end_turn(store, proposal.id))

    assert updated is not None
    assert (updated.lock_holder, updated.lock_expires_at, updated.current_turn_id) == (
        None,
        None,
        None,
    )


def test_story_4_5_begin_turn_binds_the_given_tid() -> None:
    proposal = _proposal(owner_oid=OWNER_A, lock_holder=None, lock_expires_at=None)
    store = FakeProposalStore([proposal])
    tid = uuid4()

    updated = asyncio.run(begin_turn(store, proposal.id, FakeClock(), tid))

    assert updated is not None
    assert updated.current_turn_id == tid


def test_story_4_5_end_turn_hands_the_lock_back_to_a_session() -> None:
    proposal = _proposal(owner_oid=OWNER_A, lock_holder="ai", current_turn_id=uuid4())
    store = FakeProposalStore([proposal])
    clock = FakeClock()
    expires_at = clock.now() + LOCK_DURATION

    updated = asyncio.run(
        end_turn(store, proposal.id, lock_holder=SESSION_ID, lock_expires_at=expires_at)
    )

    assert updated is not None
    assert (updated.lock_holder, updated.lock_expires_at, updated.current_turn_id) == (
        SESSION_ID,
        expires_at,
        None,
    )


# --- Story 4.5: start_chat_turn (spine AD-4, AD-9, AD-16) -----------------------------------


def test_story_4_5_start_chat_turn_moves_the_lock_to_ai_with_the_given_tid() -> None:
    proposal = _proposal(owner_oid=OWNER_A, lock_holder=SESSION_ID)
    clock = FakeClock()
    tid = uuid4()

    updated = start_chat_turn(proposal, SESSION_ID, tid, clock)

    assert updated.lock_holder == "ai"
    assert updated.lock_expires_at == clock.now() + AI_TURN_SAFETY_WINDOW
    assert updated.current_turn_id == tid


def test_story_4_5_start_chat_turn_rejects_a_submitted_proposal() -> None:
    proposal = _proposal(
        owner_oid=OWNER_A, lock_holder=SESSION_ID, status=ProposalStatus.SUBMITTED
    )

    with pytest.raises(DomainError) as excinfo:
        start_chat_turn(proposal, SESSION_ID, uuid4(), FakeClock())
    [error] = excinfo.value.errors
    assert error.code == ErrorCode.PROPOSAL_SUBMITTED


def test_story_4_5_start_chat_turn_rejects_a_turn_already_running() -> None:
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _proposal(
        owner_oid=OWNER_A,
        lock_holder="ai",
        lock_expires_at=now + timedelta(minutes=1),
        current_turn_id=uuid4(),
        now=now,
    )

    with pytest.raises(DomainError) as excinfo:
        start_chat_turn(proposal, SESSION_ID, uuid4(), FakeClock(now))
    [error] = excinfo.value.errors
    assert error.code == ErrorCode.TURN_IN_PROGRESS


def test_story_4_5_start_chat_turn_rejects_a_turn_already_running_even_for_the_owning_session() -> (
    None
):
    """A live ai turn already means the caller's own session can't hold the lock either -- the
    error must still read as turn_in_progress, not lock_not_held (AC7 vs AC8)."""
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _proposal(
        owner_oid=OWNER_A,
        lock_holder="ai",
        lock_expires_at=now + timedelta(minutes=1),
        current_turn_id=uuid4(),
        now=now,
    )

    with pytest.raises(DomainError) as excinfo:
        start_chat_turn(proposal, SESSION_ID, uuid4(), FakeClock(now))
    [error] = excinfo.value.errors
    assert error.code == ErrorCode.TURN_IN_PROGRESS


def test_story_4_5_start_chat_turn_allows_a_turn_whose_safety_expiry_has_passed() -> (
    None
):
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _proposal(
        owner_oid=OWNER_A,
        lock_holder=SESSION_ID,
        lock_expires_at=now + timedelta(days=1),
        now=now,
    )
    # A previous ai turn's safety window elapsed, but the human session's own lock is live: this
    # must succeed (no turn is actually running any more).
    proposal = replace(proposal, current_turn_id=uuid4())

    updated = start_chat_turn(proposal, SESSION_ID, uuid4(), FakeClock(now))

    assert updated.lock_holder == "ai"


def test_story_4_5_start_chat_turn_rejects_no_lock() -> None:
    proposal = _proposal(owner_oid=OWNER_A, lock_holder=OTHER_SESSION_ID)

    with pytest.raises(DomainError) as excinfo:
        start_chat_turn(proposal, SESSION_ID, uuid4(), FakeClock())
    [error] = excinfo.value.errors
    assert error.code == ErrorCode.LOCK_NOT_HELD


def test_story_4_5_start_chat_turn_rejects_an_expired_lock() -> None:
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _proposal(
        owner_oid=OWNER_A,
        lock_holder=SESSION_ID,
        lock_expires_at=now - timedelta(seconds=1),
        now=now,
    )

    with pytest.raises(DomainError) as excinfo:
        start_chat_turn(proposal, SESSION_ID, uuid4(), FakeClock(now))
    [error] = excinfo.value.errors
    assert error.code == ErrorCode.LOCK_NOT_HELD


# Story 3.2: apply_answers rejects a write to a submitted proposal (AD-2, AD-8), and draft_view
# echoes submitted_at.


def test_story_3_2_apply_answers_rejects_a_write_to_a_submitted_proposal() -> None:
    proposal = _proposal(
        schema_version=1, status=ProposalStatus.SUBMITTED, answers=_answers(C1="Ally")
    )

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"C1": "Bob"}, FakeClock(), (), SESSION_ID)

    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("proposal", ErrorCode.PROPOSAL_SUBMITTED)
    # Raised before anything is touched: the original, frozen fixture proves nothing changed.
    assert proposal.answers["C1"]["value"] == "Ally"


def test_story_3_2_apply_answers_rejects_a_submitted_proposal_before_the_lock_check() -> (
    None
):
    # No lock held at all (spec Code Map: "a submitted proposal has no meaningful lock state to
    # check") -- proposal_submitted still outranks lock_not_held.
    proposal = _proposal(
        schema_version=1, status=ProposalStatus.SUBMITTED, lock_holder=None
    )

    with pytest.raises(DomainError) as excinfo:
        apply_answers(SCHEMA, proposal, 0, {"C1": "Ally"}, FakeClock(), (), SESSION_ID)

    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("proposal", ErrorCode.PROPOSAL_SUBMITTED)


def test_story_3_2_apply_answers_stale_revision_still_returns_none_for_a_submitted_proposal() -> (
    None
):
    # The revision guard runs before the submitted check too (mirrors the lock-check ordering
    # test above): a stale expected_revision returns None with no exception either way.
    proposal = _proposal(schema_version=1, status=ProposalStatus.SUBMITTED)

    assert (
        apply_answers(SCHEMA, proposal, 5, {"C1": "Ally"}, FakeClock(), (), SESSION_ID)
        is None
    )


def test_story_3_2_draft_view_echoes_submitted_at() -> None:
    submitted = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
    proposal = _proposal(status=ProposalStatus.SUBMITTED, submitted_at=submitted)

    assert draft_view(proposal, SESSION_ID)["submitted_at"] == submitted


# Story 3.3/FORM-21: submit_proposal (declaration, AI-rating feedback and the real submit, AD-2,
# AD-8, AD-12, AD-13, AD-16). Reuses COMPLETE_ANSWERS/_complete_proposal from the Story 3.1 section
# above: a clean, valid, complete draft with the lock held by SESSION_ID (the _proposal default).

_COLUMNS = db_columns(SCHEMA)
_FEEDBACK = {"rating": 4, "comment": "Saved me a lot of typing."}
# _complete_proposal's lock (via _proposal's own default) is held by SESSION_ID until one day
# after ALLY_CREATED: every test below that needs the lock check to pass reads the clock an hour
# after that, well inside the window, rather than FakeClock()'s own default (2026-09-26T09:00),
# which would already be past it.
_SUBMIT_NOW = ALLY_CREATED + timedelta(hours=1)


def test_story_3_3_submit_happy_path_new_customer() -> None:
    proposal = _complete_proposal()
    clock = FakeClock(_SUBMIT_NOW)

    result = asyncio.run(
        submit_proposal(
            SCHEMA,
            proposal,
            proposal.revision,
            True,
            _FEEDBACK,
            clock,
            FakeCatalogue([_fsh()]),
            SESSION_ID,
            _COLUMNS,
        )
    )

    assert result is not None
    updated = result.proposal
    assert updated.status is ProposalStatus.SUBMITTED
    assert updated.submitted_at == clock.now()
    assert updated.revision == proposal.revision + 1
    assert updated.answers["D1"] == {
        "value": True,
        "source": "human",
        "updated_at": "2026-09-25T04:00:00Z",
    }
    # No customer_id on the incoming proposal: a fresh one is generated (AD-13), so the store can
    # tell an insert from an update without touching the database itself.
    assert proposal.customer_id is None
    assert updated.customer_id is not None
    assert result.customer_values["first_name"] == "Ally"
    assert result.customer_values["last_name"] == "Macbeal"
    assert result.customer_values["date_of_birth"] == date(1994, 11, 20)
    assert result.feedback.rating == 4
    assert result.feedback.comment == "Saved me a lot of typing."


def test_story_3_3_submit_happy_path_linked_customer_keeps_the_existing_id() -> None:
    existing_id = uuid4()
    proposal = replace(_complete_proposal(), customer_id=existing_id)

    result = asyncio.run(
        submit_proposal(
            SCHEMA,
            proposal,
            proposal.revision,
            True,
            _FEEDBACK,
            FakeClock(_SUBMIT_NOW),
            FakeCatalogue([_fsh()]),
            SESSION_ID,
            _COLUMNS,
        )
    )

    assert result is not None
    assert result.proposal.customer_id == existing_id  # unchanged, never regenerated


def test_story_3_3_missing_declaration_is_declaration_required() -> None:
    proposal = _complete_proposal()

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(
            submit_proposal(
                SCHEMA,
                proposal,
                proposal.revision,
                False,
                _FEEDBACK,
                FakeClock(_SUBMIT_NOW),
                FakeCatalogue([_fsh()]),
                SESSION_ID,
                _COLUMNS,
            )
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("declaration", ErrorCode.DECLARATION_REQUIRED)


@pytest.mark.parametrize(
    "rating",
    [
        pytest.param(None, id="missing"),
        pytest.param(0, id="below range"),
        pytest.param(6, id="above range"),
        pytest.param(True, id="a bool, not a real rating"),
    ],
)
def test_story_3_3_bad_rating_is_feedback_required(rating: object) -> None:
    proposal = _complete_proposal()

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(
            submit_proposal(
                SCHEMA,
                proposal,
                proposal.revision,
                True,
                {"rating": rating, "comment": None},
                FakeClock(_SUBMIT_NOW),
                FakeCatalogue([_fsh()]),
                SESSION_ID,
                _COLUMNS,
            )
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("feedback", ErrorCode.FEEDBACK_REQUIRED)


def test_story_3_3_declaration_and_feedback_errors_combine_into_one_domainerror() -> (
    None
):
    proposal = _complete_proposal()

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(
            submit_proposal(
                SCHEMA,
                proposal,
                proposal.revision,
                False,
                {"rating": None, "comment": None},
                FakeClock(_SUBMIT_NOW),
                FakeCatalogue([_fsh()]),
                SESSION_ID,
                _COLUMNS,
            )
        )
    assert {(error.field, error.code) for error in excinfo.value.errors} == {
        ("declaration", ErrorCode.DECLARATION_REQUIRED),
        ("feedback", ErrorCode.FEEDBACK_REQUIRED),
    }


def test_story_3_3_fails_validation_reuses_validate_proposals_own_errors() -> None:
    proposal = _complete_proposal(omit=("H1",))  # missing a required field

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(
            submit_proposal(
                SCHEMA,
                proposal,
                proposal.revision,
                True,
                _FEEDBACK,
                FakeClock(_SUBMIT_NOW),
                FakeCatalogue([_fsh()]),
                SESSION_ID,
                _COLUMNS,
            )
        )
    assert [(error.field, error.code) for error in excinfo.value.errors] == [
        ("H1", ErrorCode.REQUIRED)
    ]


def test_story_3_3_stale_revision_returns_none_and_writes_nothing() -> None:
    proposal = _complete_proposal()

    result = asyncio.run(
        submit_proposal(
            SCHEMA,
            proposal,
            proposal.revision + 5,
            True,
            _FEEDBACK,
            FakeClock(),
            FakeCatalogue([_fsh()]),
            SESSION_ID,
            _COLUMNS,
        )
    )

    assert result is None


def test_story_3_3_already_submitted_raises_proposal_submitted() -> None:
    proposal = replace(_complete_proposal(), status=ProposalStatus.SUBMITTED)

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(
            submit_proposal(
                SCHEMA,
                proposal,
                proposal.revision,
                True,
                _FEEDBACK,
                FakeClock(),
                FakeCatalogue([_fsh()]),
                SESSION_ID,
                _COLUMNS,
            )
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("proposal", ErrorCode.PROPOSAL_SUBMITTED)


def test_story_3_3_already_submitted_outranks_lock_not_held() -> None:
    # Mirrors apply_answers's own ordering test (Story 3.2): a submitted proposal has no
    # meaningful lock state to check, whatever session_id or the stored lock_holder say.
    proposal = replace(
        _complete_proposal(), status=ProposalStatus.SUBMITTED, lock_holder=None
    )

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(
            submit_proposal(
                SCHEMA,
                proposal,
                proposal.revision,
                True,
                _FEEDBACK,
                FakeClock(),
                FakeCatalogue([_fsh()]),
                SESSION_ID,
                _COLUMNS,
            )
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("proposal", ErrorCode.PROPOSAL_SUBMITTED)


def test_story_3_3_lock_not_held_by_the_caller_is_rejected() -> None:
    base = _complete_proposal()
    proposal = replace(
        base,
        lock_holder=OTHER_SESSION_ID,
        lock_expires_at=base.created_at + timedelta(days=1),
    )

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(
            submit_proposal(
                SCHEMA,
                proposal,
                proposal.revision,
                True,
                _FEEDBACK,
                FakeClock(),
                FakeCatalogue([_fsh()]),
                SESSION_ID,
                _COLUMNS,
            )
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("lock", ErrorCode.LOCK_NOT_HELD)


def test_story_3_3_stale_revision_checked_before_submitted_or_lock() -> None:
    proposal = replace(
        _complete_proposal(), status=ProposalStatus.SUBMITTED, lock_holder=None
    )

    result = asyncio.run(
        submit_proposal(
            SCHEMA,
            proposal,
            proposal.revision + 1,
            True,
            _FEEDBACK,
            FakeClock(),
            FakeCatalogue([_fsh()]),
            SESSION_ID,
            _COLUMNS,
        )
    )

    assert result is None  # no exception: the stale-revision guard runs first


def test_story_3_3_fake_store_submit_end_to_end() -> None:
    complete = _complete_proposal()
    store = FakeProposalStore([complete])
    clock = FakeClock(_SUBMIT_NOW)

    async def apply(current: Proposal) -> SubmitResult | None:
        return await submit_proposal(
            SCHEMA,
            current,
            complete.revision,
            True,
            _FEEDBACK,
            clock,
            FakeCatalogue([_fsh()]),
            SESSION_ID,
            _COLUMNS,
        )

    updated = asyncio.run(store.submit(complete.id, complete.revision, apply))
    assert updated is not None
    assert updated.status is ProposalStatus.SUBMITTED

    stale = asyncio.run(store.submit(complete.id, complete.revision, apply))
    assert stale is None  # the fixture's own revision moved on after the first submit


# --- Story 5.2: link_customer (spine AD-3, AD-13, AD-15) --------------------------------------

_LINK_CUSTOMER_ID = uuid4()


def _customer_row(**overrides: object) -> dict[str, object]:
    """A full, valid customer row (all 15 ``x-fill: db`` columns), synthetic data only."""
    row: dict[str, object] = {
        "first_name": "Ally",
        "last_name": "Macbeal",
        "date_of_birth": date(1994, 11, 20),
        "sex_at_birth": "female",
        "country_of_origin": "Malaysia",
        "country_of_residence": "Malaysia",
        "id_number": "940101-01-1234",
        "email": "ally@example.com",
        "mobile": "+60123456789",
        "street_address": "1 Jalan Test",
        "city": "Petaling Jaya",
        "postcode": "46000",
        "occupation": "Engineer",
        "marital_status": "single",
        "income_range": "5000-10000",
    }
    row.update(overrides)
    return row


def test_story_5_2_link_customer_copies_c1_c15_at_source_db() -> None:
    proposal = _ai_proposal()

    updated, skipped = link_customer(
        SCHEMA,
        proposal,
        _LINK_CUSTOMER_ID,
        _customer_row(),
        FakeClock(),
        _claims(),
        _COLUMNS,
    )

    assert updated.customer_id == _LINK_CUSTOMER_ID
    assert skipped == []
    assert updated.answers["C1"] == {
        "value": "Ally",
        "source": "db",
        "updated_at": "2026-09-26T09:00:00Z",
    }
    assert updated.answers["C13"]["value"] == "Macbeal"
    assert updated.answers["C2"] == {
        "value": "1994-11-20",  # a real date column, stored as its ISO string
        "source": "db",
        "updated_at": "2026-09-26T09:00:00Z",
    }
    assert updated.revision == proposal.revision + 1
    assert updated.updated_at == FakeClock().now()


def test_story_5_2_link_customer_skips_a_field_alice_already_set() -> None:
    proposal = _ai_proposal(answers=_answers(C7="alice@example.com"))

    updated, skipped = link_customer(
        SCHEMA,
        proposal,
        _LINK_CUSTOMER_ID,
        _customer_row(email="ally@example.com"),
        FakeClock(),
        _claims(),
        _COLUMNS,
    )

    assert skipped == ["C7"]
    assert updated.answers["C7"] == {
        "value": "alice@example.com",
        "source": "human",
        "updated_at": "2026-09-27T00:00:00Z",
    }  # unchanged: never overwritten by the linked record
    # every other column is still copied, human field aside
    assert updated.answers["C1"]["source"] == "db"


def test_story_5_2_link_customer_never_touches_h_or_g_answers() -> None:
    """AD-13: link_customer's own copy loop only ever writes ``customer_columns`` (C1-C15,
    never H*/G*, whatever the schema version). C3 (sex_at_birth) newly answered can activate a
    gender-specific H/G question, which AD-15's shared ``_recompute`` then defaults to "No" at
    ``source: "default"`` -- that's the same recompute every other write path already does, not
    an answer link_customer itself wrote or copied from any earlier proposal."""
    proposal = _ai_proposal()

    updated, _skipped = link_customer(
        SCHEMA,
        proposal,
        _LINK_CUSTOMER_ID,
        _customer_row(),
        FakeClock(),
        _claims(),
        _COLUMNS,
    )

    written_ids = {column.question_id for column in _COLUMNS} - set(_skipped)
    assert written_ids  # something was actually copied
    assert all(updated.answers[qid]["source"] == "db" for qid in written_ids)
    h_or_g_sources = {
        qid: entry["source"]
        for qid, entry in updated.answers.items()
        if qid.startswith(("H", "G"))
    }
    # never "db": nothing here was copied from the customer record, only recompute-defaulted.
    assert all(source == "default" for source in h_or_g_sources.values())


def test_story_5_2_link_customer_rejects_an_unknown_customer() -> None:
    proposal = _ai_proposal()

    with pytest.raises(DomainError) as excinfo:
        link_customer(
            SCHEMA, proposal, _LINK_CUSTOMER_ID, None, FakeClock(), _claims(), _COLUMNS
        )
    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("customer_id", ErrorCode.INVALID_VALUE)
    assert proposal.customer_id is None  # nothing changed


def test_story_5_2_link_customer_rejects_a_submitted_proposal() -> None:
    proposal = _ai_proposal(status=ProposalStatus.SUBMITTED)

    with pytest.raises(DomainError) as excinfo:
        link_customer(
            SCHEMA,
            proposal,
            _LINK_CUSTOMER_ID,
            _customer_row(),
            FakeClock(),
            _claims(),
            _COLUMNS,
        )
    [error] = excinfo.value.errors
    assert error.code == ErrorCode.PROPOSAL_SUBMITTED


def test_story_5_2_link_customer_rejects_when_not_turn_bound() -> None:
    proposal = _ai_proposal(lock_holder=SESSION_ID)

    with pytest.raises(DomainError) as excinfo:
        link_customer(
            SCHEMA,
            proposal,
            _LINK_CUSTOMER_ID,
            _customer_row(),
            FakeClock(),
            _claims(),
            _COLUMNS,
        )
    [error] = excinfo.value.errors
    assert error.code == ErrorCode.LOCK_NOT_HELD


def test_story_5_2_link_customer_recomputes_the_active_set() -> None:
    # A pre-existing x-simple default (Y3, AD-15) survives a link that touches unrelated fields.
    proposal = _ai_proposal(
        answers={
            "Y3": {
                "value": "No",
                "source": "default",
                "updated_at": "2026-09-27T00:00:00Z",
            }
        }
    )

    updated, _skipped = link_customer(
        SCHEMA,
        proposal,
        _LINK_CUSTOMER_ID,
        _customer_row(),
        FakeClock(),
        _claims(),
        _COLUMNS,
    )

    assert updated.answers["Y3"] == {
        "value": "No",
        "source": "default",
        "updated_at": "2026-09-27T00:00:00Z",
    }


# --- Story FORM-227: delete_draft (spine AD-2, AD-8) --------------------------------------------
#
# _lock_blocks_delete is exercised only through delete_draft (spec Boundaries), the same convention
# every other private lock/turn predicate in this module already follows (_lock_held_by,
# _turn_running are never tested directly either).


def test_form_227_delete_draft_removes_an_owned_draft_with_no_lock_or_turn() -> None:
    proposal = _proposal(owner_oid=OWNER_A, lock_holder=None)
    store = FakeProposalStore([proposal])

    asyncio.run(delete_draft(store, proposal.id, OWNER_A, SESSION_ID, FakeClock()))

    assert asyncio.run(store.get(proposal.id)) is None


def test_form_227_delete_draft_404s_the_same_for_unowned_or_missing() -> None:
    proposal = _proposal(owner_oid=OWNER_A, lock_holder=None)
    store = FakeProposalStore([proposal])

    with pytest.raises(ProposalNotFoundError):
        asyncio.run(delete_draft(store, proposal.id, OWNER_B, SESSION_ID, FakeClock()))
    with pytest.raises(ProposalNotFoundError):
        asyncio.run(delete_draft(store, uuid4(), OWNER_A, SESSION_ID, FakeClock()))
    # Neither attempt touched the stored row.
    assert asyncio.run(store.get(proposal.id)) is not None


def test_form_227_delete_draft_rejects_a_submitted_proposal_and_deletes_nothing() -> None:
    proposal = _proposal(
        owner_oid=OWNER_A, status=ProposalStatus.SUBMITTED, lock_holder=None
    )
    store = FakeProposalStore([proposal])

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(delete_draft(store, proposal.id, OWNER_A, SESSION_ID, FakeClock()))

    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("proposal", ErrorCode.PROPOSAL_SUBMITTED)
    assert asyncio.run(store.get(proposal.id)) is not None


def test_form_227_delete_draft_rejects_a_live_ai_turn_and_deletes_nothing() -> None:
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _proposal(
        owner_oid=OWNER_A,
        now=now,
        lock_holder="ai",
        lock_expires_at=now + AI_TURN_SAFETY_WINDOW,
    )
    store = FakeProposalStore([proposal])

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(
            delete_draft(store, proposal.id, OWNER_A, SESSION_ID, FakeClock(now))
        )

    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("turn", ErrorCode.TURN_IN_PROGRESS)
    assert asyncio.run(store.get(proposal.id)) is not None


def test_form_227_delete_draft_rejects_a_different_sessions_live_lock() -> None:
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    proposal = _proposal(
        owner_oid=OWNER_A,
        now=now,
        lock_holder=OTHER_SESSION_ID,
        lock_expires_at=now + timedelta(seconds=30),
    )
    store = FakeProposalStore([proposal])

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(
            delete_draft(store, proposal.id, OWNER_A, SESSION_ID, FakeClock(now))
        )

    [error] = excinfo.value.errors
    assert (error.field, error.code) == ("lock", ErrorCode.LOCK_NOT_HELD)
    assert asyncio.run(store.get(proposal.id)) is not None


@pytest.mark.parametrize(
    ("lock_holder", "lock_expires_at"),
    [
        (None, None),  # never acquired: free
        (SESSION_ID, None),  # the caller's own session, expiry computed by _proposal's default
        (OTHER_SESSION_ID, "expired"),  # a different session, but its lock has lapsed
    ],
)
def test_form_227_delete_draft_proceeds_when_the_lock_doesnt_block_it(
    lock_holder: str | None, lock_expires_at: object
) -> None:
    now = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    expires_at = (
        now - timedelta(seconds=1)
        if lock_expires_at == "expired"
        else (now + timedelta(seconds=30) if lock_holder == SESSION_ID else None)
    )
    proposal = _proposal(
        owner_oid=OWNER_A, now=now, lock_holder=lock_holder, lock_expires_at=expires_at
    )
    store = FakeProposalStore([proposal])

    asyncio.run(delete_draft(store, proposal.id, OWNER_A, SESSION_ID, FakeClock(now)))

    assert asyncio.run(store.get(proposal.id)) is None


def test_form_227_delete_draft_never_deletes_the_conversation_id() -> None:
    # delete_draft never touches conversation_id at all (spec Boundaries: it's left orphaned) --
    # the fake store's delete simply removes the whole row, so this only documents the intent
    # rather than asserting any behaviour delete_draft itself owns.
    proposal = _proposal(owner_oid=OWNER_A, lock_holder=None)
    proposal = replace(proposal, conversation_id="synthetic-conversation-id")
    store = FakeProposalStore([proposal])

    asyncio.run(delete_draft(store, proposal.id, OWNER_A, SESSION_ID, FakeClock()))

    assert asyncio.run(store.get(proposal.id)) is None
