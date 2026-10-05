"""Story 4.3: turn tokens (`issue_turn_token`, `decode_turn_token`, `resolve_turn`), spine AD-4.

Unit tests only, against a `FakeProposalStore` -- no database needed.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from pydantic import SecretStr

from domain.errors import DomainError, ErrorCode
from domain.proposals import Proposal, ProposalNotFoundError, ProposalStatus
from domain.turn_tokens import (
    TURN_TOKEN_TTL,
    TurnTokenClaims,
    TurnTokenError,
    decode_turn_token,
    issue_turn_token,
    resolve_turn,
)
from tests.fakes import FakeClock

OWNER_A = "synthetic-owner-a"
OWNER_B = "synthetic-owner-b"
SIGNING_KEY = SecretStr("synthetic-signing-key-" * 2)
OTHER_SIGNING_KEY = SecretStr("another-signing-key-" * 2)


def _proposal(
    *,
    owner_oid: str = OWNER_A,
    status: ProposalStatus = ProposalStatus.DRAFT,
    lock_holder: str | None = "ai",
    lock_expires_at: datetime | None = None,
    current_turn_id: UUID | None = None,
    now: datetime | None = None,
) -> Proposal:
    at = now or datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    return Proposal(
        id=uuid4(),
        customer_id=None,
        owner_oid=owner_oid,
        owner_seq=1,
        schema_version=1,
        status=status,
        revision=0,
        conversation_id=None,
        answers={},
        created_at=at,
        updated_at=at,
        lock_holder=lock_holder,
        lock_expires_at=lock_expires_at if lock_expires_at is not None else at + timedelta(minutes=1),
        current_turn_id=current_turn_id,
        submitted_at=None,
    )


class FakeProposalStore:
    """A minimal in-memory ``ProposalStore`` (spine AD-8), just enough for turn-token tests."""

    def __init__(self, proposals: Sequence[Proposal] = ()) -> None:
        self._proposals: dict[UUID, Proposal] = {p.id: p for p in proposals}

    async def create(self, **_: Any) -> Proposal:  # pragma: no cover -- unused here
        raise NotImplementedError

    async def get(self, proposal_id: UUID) -> Proposal | None:
        return self._proposals.get(proposal_id)

    async def list_for_owner(
        self, owner_oid: str, status: ProposalStatus
    ) -> Sequence[Proposal]:  # pragma: no cover -- unused here
        raise NotImplementedError

    async def update_answers(
        self,
        proposal_id: UUID,
        expected_revision: int,
        apply: Callable[[Proposal], Proposal | None],
        *,
        model_deployment: str = "test-model-deployment",
        overridden_by: str = "test-overridden-by",
    ) -> Proposal | None:  # pragma: no cover -- unused here
        raise NotImplementedError

    async def acquire_lock(
        self, *args: Any, **kwargs: Any
    ) -> Proposal | None:  # pragma: no cover -- unused here
        raise NotImplementedError

    async def apply_agent_patch(
        self, proposal_id: UUID, apply: Callable[[Proposal], Proposal | None]
    ) -> Proposal | None:  # pragma: no cover -- unused here
        raise NotImplementedError

    async def set_turn(self, proposal_id: UUID, **changes: Any) -> Proposal | None:
        current = self._proposals.get(proposal_id)
        if current is None:
            return None
        updated = replace(current, **changes)
        self._proposals[proposal_id] = updated
        return updated


# --- issue_turn_token ---------------------------------------------------------------------------


def test_story_4_3_issue_turn_token_refuses_a_non_owner() -> None:
    proposal = _proposal(owner_oid=OWNER_A)
    store = FakeProposalStore([proposal])

    with pytest.raises(ProposalNotFoundError):
        asyncio.run(
            issue_turn_token(store, proposal.id, OWNER_B, FakeClock(), SIGNING_KEY)
        )


def test_story_4_3_issue_turn_token_mints_a_claim_shaped_jwt() -> None:
    proposal = _proposal(owner_oid=OWNER_A)
    store = FakeProposalStore([proposal])
    clock = FakeClock()

    token = asyncio.run(
        issue_turn_token(store, proposal.id, OWNER_A, clock, SIGNING_KEY)
    )
    claims = decode_turn_token(token, SIGNING_KEY, clock)

    assert claims.sub == OWNER_A
    assert claims.pid == proposal.id
    assert isinstance(claims.tid, UUID)
    assert claims.exp == clock.now() + TURN_TOKEN_TTL


def test_story_4_3_issue_turn_token_mints_a_fresh_tid_each_time() -> None:
    proposal = _proposal(owner_oid=OWNER_A)
    store = FakeProposalStore([proposal])
    clock = FakeClock()

    first = decode_turn_token(
        asyncio.run(issue_turn_token(store, proposal.id, OWNER_A, clock, SIGNING_KEY)),
        SIGNING_KEY,
        clock,
    )
    second = decode_turn_token(
        asyncio.run(issue_turn_token(store, proposal.id, OWNER_A, clock, SIGNING_KEY)),
        SIGNING_KEY,
        clock,
    )

    assert first.tid != second.tid


def test_story_4_3_the_signing_key_never_appears_in_the_token(monkeypatch: Any) -> None:
    proposal = _proposal(owner_oid=OWNER_A)
    store = FakeProposalStore([proposal])

    token = asyncio.run(
        issue_turn_token(store, proposal.id, OWNER_A, FakeClock(), SIGNING_KEY)
    )

    assert SIGNING_KEY.get_secret_value() not in token


# --- decode_turn_token ---------------------------------------------------------------------------


def _token_for(claims: dict[str, Any], key: SecretStr = SIGNING_KEY) -> str:
    return jwt.encode(claims, key.get_secret_value(), algorithm="HS256")


def test_story_4_3_decode_turn_token_round_trips_a_valid_token() -> None:
    clock = FakeClock()
    pid, tid = uuid4(), uuid4()
    token = _token_for(
        {"sub": OWNER_A, "pid": str(pid), "tid": str(tid), "exp": clock.now() + timedelta(minutes=1)}
    )

    claims = decode_turn_token(token, SIGNING_KEY, clock)

    assert claims == TurnTokenClaims(sub=OWNER_A, pid=pid, tid=tid, exp=clock.now() + timedelta(minutes=1))


def test_story_4_3_decode_turn_token_rejects_a_forged_signature() -> None:
    clock = FakeClock()
    token = _token_for(
        {"sub": OWNER_A, "pid": str(uuid4()), "tid": str(uuid4()), "exp": clock.now() + timedelta(minutes=1)},
        key=OTHER_SIGNING_KEY,
    )

    with pytest.raises(TurnTokenError):
        decode_turn_token(token, SIGNING_KEY, clock)


def test_story_4_3_decode_turn_token_rejects_malformed_text() -> None:
    with pytest.raises(TurnTokenError):
        decode_turn_token("not-a-jwt-at-all", SIGNING_KEY, FakeClock())


def test_story_4_3_decode_turn_token_rejects_a_missing_claim() -> None:
    clock = FakeClock()
    token = _token_for({"sub": OWNER_A, "pid": str(uuid4()), "exp": clock.now() + timedelta(minutes=1)})

    with pytest.raises(TurnTokenError):
        decode_turn_token(token, SIGNING_KEY, clock)


def test_story_4_3_decode_turn_token_rejects_a_non_uuid_pid() -> None:
    clock = FakeClock()
    token = _token_for(
        {"sub": OWNER_A, "pid": "not-a-uuid", "tid": str(uuid4()), "exp": clock.now() + timedelta(minutes=1)}
    )

    with pytest.raises(TurnTokenError):
        decode_turn_token(token, SIGNING_KEY, clock)


def test_story_4_3_decode_turn_token_rejects_an_expired_token() -> None:
    clock = FakeClock()
    token = _token_for(
        {"sub": OWNER_A, "pid": str(uuid4()), "tid": str(uuid4()), "exp": clock.now() + timedelta(minutes=1)}
    )

    clock.advance(timedelta(minutes=1))  # exactly at exp: already expired (spec: now >= exp)

    with pytest.raises(TurnTokenError):
        decode_turn_token(token, SIGNING_KEY, clock)


def test_story_4_3_decode_turn_token_accepts_a_token_still_short_of_expiry() -> None:
    clock = FakeClock()
    token = _token_for(
        {"sub": OWNER_A, "pid": str(uuid4()), "tid": str(uuid4()), "exp": clock.now() + timedelta(minutes=1)}
    )

    clock.advance(timedelta(seconds=59))

    decode_turn_token(token, SIGNING_KEY, clock)  # does not raise


# --- resolve_turn --------------------------------------------------------------------------------


def test_story_4_3_resolve_turn_returns_the_proposal_when_bound() -> None:
    clock = FakeClock()
    tid = uuid4()
    proposal = _proposal(owner_oid=OWNER_A, current_turn_id=tid, now=clock.now())
    store = FakeProposalStore([proposal])
    token = _token_for(
        {"sub": OWNER_A, "pid": str(proposal.id), "tid": str(tid), "exp": clock.now() + timedelta(minutes=1)}
    )

    resolved = asyncio.run(resolve_turn(store, token, SIGNING_KEY, clock))

    assert resolved == proposal


def test_story_4_3_resolve_turn_rejects_a_tampered_pid() -> None:
    clock = FakeClock()
    proposal = _proposal(owner_oid=OWNER_A, current_turn_id=uuid4(), now=clock.now())
    store = FakeProposalStore([proposal])
    token = _token_for(
        {"sub": OWNER_A, "pid": str(uuid4()), "tid": str(uuid4()), "exp": clock.now() + timedelta(minutes=1)}
    )

    with pytest.raises(TurnTokenError):
        asyncio.run(resolve_turn(store, token, SIGNING_KEY, clock))


def test_story_4_3_resolve_turn_rejects_another_agents_own_valid_token() -> None:
    """Agent B's own genuinely-issued token, naming Agent A's proposal via a swapped pid, is
    rejected the same as any other mismatch -- an owner check, not just a signature check."""
    clock = FakeClock()
    tid = uuid4()
    proposal_a = _proposal(owner_oid=OWNER_A, current_turn_id=tid, now=clock.now())
    store = FakeProposalStore([proposal_a])
    token = _token_for(
        {"sub": OWNER_B, "pid": str(proposal_a.id), "tid": str(tid), "exp": clock.now() + timedelta(minutes=1)}
    )

    with pytest.raises(TurnTokenError):
        asyncio.run(resolve_turn(store, token, SIGNING_KEY, clock))


def test_story_4_3_resolve_turn_rejects_a_stale_tid() -> None:
    """A turn token from an earlier turn, replayed after a new turn began."""
    clock = FakeClock()
    old_tid = uuid4()
    proposal = _proposal(owner_oid=OWNER_A, current_turn_id=uuid4(), now=clock.now())
    store = FakeProposalStore([proposal])
    token = _token_for(
        {"sub": OWNER_A, "pid": str(proposal.id), "tid": str(old_tid), "exp": clock.now() + timedelta(minutes=1)}
    )

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(resolve_turn(store, token, SIGNING_KEY, clock))
    assert excinfo.value.errors[0].code is ErrorCode.LOCK_NOT_HELD


def test_story_4_3_resolve_turn_rejects_when_the_lock_isnt_held_by_ai() -> None:
    clock = FakeClock()
    tid = uuid4()
    proposal = _proposal(
        owner_oid=OWNER_A, lock_holder="a-human-session", current_turn_id=tid, now=clock.now()
    )
    store = FakeProposalStore([proposal])
    token = _token_for(
        {"sub": OWNER_A, "pid": str(proposal.id), "tid": str(tid), "exp": clock.now() + timedelta(minutes=1)}
    )

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(resolve_turn(store, token, SIGNING_KEY, clock))
    assert excinfo.value.errors[0].code is ErrorCode.LOCK_NOT_HELD


def test_story_4_3_resolve_turn_rejects_an_expired_lock() -> None:
    clock = FakeClock()
    tid = uuid4()
    proposal = _proposal(
        owner_oid=OWNER_A,
        current_turn_id=tid,
        now=clock.now(),
        lock_expires_at=clock.now() - timedelta(seconds=1),
    )
    store = FakeProposalStore([proposal])
    token = _token_for(
        {"sub": OWNER_A, "pid": str(proposal.id), "tid": str(tid), "exp": clock.now() + timedelta(minutes=1)}
    )

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(resolve_turn(store, token, SIGNING_KEY, clock))
    assert excinfo.value.errors[0].code is ErrorCode.LOCK_NOT_HELD
