"""Story 4.5, AC16/AC17 (P0): two agents chatting on two proposals in parallel, >=200 turns each
-- each proposal ends up holding only its own owner's markers, never a cross-proposal write (spine
AD-4, AD-17). Runs the real orchestration (``open_chat_turn``/``run_chat_turn``) against a real
migrated PostgreSQL, both proposals' turn sequences genuinely interleaved by ``asyncio.gather``
(each proposal's own turns are strictly sequential -- AD-9's "one turn per proposal at a time" --
but the two proposals' sequences run concurrently with each other).

Tagged ``p0``: failure blocks merge (AC17), like the Story 4.3 attack suite.
"""

import asyncio
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from adapters.chat.stub import PatchStep, StubAgentGateway
from adapters.chat.turns import open_chat_turn, run_chat_turn
from adapters.db.engine import build_password_source, create_engine
from adapters.db.proposals import SqlProposalStore
from adapters.db.scope import for_owner, install_scope, scoped
from adapters.rest.principal import TEST_PRINCIPALS
from adapters.settings import Settings
from domain.clock import Clock
from domain.proposals import LOCK_DURATION, Proposal, ProposalStore, create_draft
from tests.fakes import FakeClock

pytestmark = pytest.mark.p0

TURNS_PER_PROPOSAL = 200
OWNER_A = TEST_PRINCIPALS["agent-a"].oid
OWNER_B = TEST_PRINCIPALS["agent-b"].oid


async def _run_turns(
    *,
    store: ProposalStore,
    engine: AsyncEngine,
    signing_key: SecretStr,
    clock: Clock,
    owner_oid: str,
    session_id: str,
    proposal_id: UUID,
    count: int,
) -> None:
    """One agent's own sequence of ``count`` chat turns on one proposal, each writing a marker
    only that owner could have written (``<owner_oid>-<index>``).

    A direct call into the chat orchestration, outside any real REST request: unlike production
    (``AuthRequiredMiddleware``), nothing sets the row-level security scope around
    ``open_chat_turn`` here, so this scopes itself to ``owner_oid`` for the whole sequence
    (AD-17). ``run_chat_turn``'s own two post-response writes scope themselves the same way, one
    call at a time; this outer scope only needs to cover ``open_chat_turn``. Each concurrent
    ``asyncio.gather`` branch gets its own task-local copy of the scope ContextVar, so agent A's
    and agent B's sequences never see each other's scope even though they interleave.
    """
    with scoped(for_owner(owner_oid)):
        for index in range(count):
            gateway = StubAgentGateway(
                engine=engine,
                signing_key=signing_key,
                clock=clock,
                script=[PatchStep({"C1": f"{owner_oid}-{index}"})],
            )
            proposal, token = await open_chat_turn(
                store=store,
                proposal_id=proposal_id,
                principal_oid=owner_oid,
                session_id=session_id,
                signing_key=signing_key,
                clock=clock,
            )
            events = [
                event
                async for event in run_chat_turn(
                    store=store,
                    gateway=gateway,
                    proposal=proposal,
                    token=token,
                    session_id=session_id,
                    message="marker",
                    clock=clock,
                    traceparent=None,
                )
            ]
            assert events[-1].event == "done", events


def test_p0_two_hundred_turns_each_on_two_proposals_in_parallel_stay_isolated(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    settings = db_settings.model_copy(
        update={"database_name": migrated_db, "formapp_test_mode": True}
    )
    engine = create_engine(settings, build_password_source(settings, clock))
    # Every SqlProposalStore transaction on this engine needs the AD-17 scope hook: production
    # gets this from create_app, but this test builds its own engine directly (AD-17).
    install_scope(engine)
    store = SqlProposalStore(engine)
    signing_key = settings.turn_token_signing_key
    session_a, session_b = "synthetic-session-a", "synthetic-session-b"

    async def scenario() -> tuple[UUID, UUID]:
        with scoped(for_owner(OWNER_A)):
            proposal_a = await create_draft(store, OWNER_A, clock)
            now = clock.now()
            await store.acquire_lock(proposal_a.id, session_a, now, now + LOCK_DURATION, False)
        with scoped(for_owner(OWNER_B)):
            proposal_b = await create_draft(store, OWNER_B, clock)
            now = clock.now()
            await store.acquire_lock(proposal_b.id, session_b, now, now + LOCK_DURATION, False)

        await asyncio.gather(
            _run_turns(
                store=store,
                engine=engine,
                signing_key=signing_key,
                clock=clock,
                owner_oid=OWNER_A,
                session_id=session_a,
                proposal_id=proposal_a.id,
                count=TURNS_PER_PROPOSAL,
            ),
            _run_turns(
                store=store,
                engine=engine,
                signing_key=signing_key,
                clock=clock,
                owner_oid=OWNER_B,
                session_id=session_b,
                proposal_id=proposal_b.id,
                count=TURNS_PER_PROPOSAL,
            ),
        )
        return proposal_a.id, proposal_b.id

    proposal_a_id, proposal_b_id = asyncio.run(scenario())

    async def _read() -> tuple[Proposal | None, Proposal | None]:
        with scoped(for_owner(OWNER_A)):
            read_a = await store.get(proposal_a_id)
        with scoped(for_owner(OWNER_B)):
            read_b = await store.get(proposal_b_id)
        return read_a, read_b

    proposal_a, proposal_b = asyncio.run(_read())

    assert proposal_a is not None
    assert proposal_b is not None
    # Every turn on a proposal is exactly one write (the scripted patch_draft always applies):
    # a stray cross-proposal write would have bumped one proposal's revision past the other's own
    # turn count, or under it.
    assert proposal_a.revision == TURNS_PER_PROPOSAL
    assert proposal_b.revision == TURNS_PER_PROPOSAL
    marker_a = proposal_a.answers["C1"]["value"]
    marker_b = proposal_b.answers["C1"]["value"]
    assert marker_a.startswith(OWNER_A) and not marker_a.startswith(OWNER_B)
    assert marker_b.startswith(OWNER_B) and not marker_b.startswith(OWNER_A)
