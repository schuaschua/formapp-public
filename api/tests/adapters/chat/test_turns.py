"""Story 4.5, 4.6: ``POST/GET /api/proposals/:id/chat`` (AD-4, AD-5, AD-7, AD-9, AD-16, AD-18).

Against a real migrated PostgreSQL, driven through a real ``TestClient`` (so the whole stack --
turn token, lock/turn transitions, SSE relay, conversation get-or-create, write logging -- is
exercised, not just the domain functions underneath), with an explicitly scripted
``StubAgentGateway`` injected via ``create_app(..., agent_gateway=...)`` (AD-18: never a real
Foundry call).
"""

import asyncio
import json
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from adapters.chat.stub import DeltaStep, FailStep, HangStep, PatchStep, StubAgentGateway
from adapters.chat.turns import open_chat_turn, run_chat_turn
from adapters.db.engine import build_password_source, create_engine
from adapters.db.proposals import SqlProposalStore
from adapters.db.scope import for_owner, install_scope, scoped
from adapters.rest.app import create_app
from adapters.rest.principal import TEST_PRINCIPALS
from adapters.settings import Settings
from domain.checklist import opening_message
from domain.proposals import AI_TURN_SAFETY_WINDOW, LOCK_DURATION, create_draft
from tests.fakes import FakeClock
from tests.support import AS_AGENT_A, AS_AGENT_B

Admin = Callable[[str], psycopg.Connection[Any]]

SESSION_A = "test-session"  # the `client` fixture's own default X-Session-Id
SESSION_B = "synthetic-session-b"


def _settings(db_settings: Settings, migrated_db: str) -> Settings:
    return db_settings.model_copy(
        update={"database_name": migrated_db, "formapp_test_mode": True}
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def _make_client(
    db_settings: Settings,
    migrated_db: str,
    clock: FakeClock,
    script: list[Any] | None,
) -> Iterator[tuple[TestClient, StubAgentGateway]]:
    settings = _settings(db_settings, migrated_db)
    # A shared engine, so the stub and the app it's injected into read/write the same database
    # connection pool.
    engine = create_engine(settings, build_password_source(settings, clock))
    stub = StubAgentGateway(
        engine=engine, signing_key=settings.turn_token_signing_key, clock=clock, script=script
    )
    with TestClient(
        create_app(settings, clock=clock, engine=engine, agent_gateway=stub),
        headers={"X-Session-Id": SESSION_A},
    ) as test_client:
        yield test_client, stub


@pytest.fixture
def happy_client(
    db_settings: Settings, migrated_db: str, clock: FakeClock
) -> Iterator[tuple[TestClient, StubAgentGateway]]:
    script = [DeltaStep("Got it. "), DeltaStep("Filled it in."), PatchStep({"C1": "Ally"})]
    yield from _make_client(db_settings, migrated_db, clock, script)


def _events(response: Any) -> list[tuple[str, dict[str, Any]]]:
    """Parses an SSE body into ``(event, data)`` pairs (AD-5: exactly ``delta``/``done``/``error``)."""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in response.text.strip().split("\n\n"):
        if not block:
            continue
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
        assert event is not None and data is not None, block
        events.append((event, data))
    return events


def _create_and_lock(client: TestClient) -> dict[str, Any]:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    client.post(
        f"/api/proposals/{created['id']}/lock",
        json={"take_over": False},
        headers=AS_AGENT_A,
    )
    return created


def _insert_draft(
    admin: Admin,
    dbname: str,
    *,
    owner_oid: str,
    status: str = "draft",
    lock_holder: str | None = None,
    lock_expires_at: str | None = None,
    current_turn_id: UUID | None = None,
) -> UUID:
    with admin(dbname) as connection:
        row = connection.execute(
            "INSERT INTO proposal "
            "(owner_oid, owner_seq, schema_version, status, revision, answers, "
            "created_at, updated_at, lock_holder, lock_expires_at, current_turn_id) "
            "VALUES (%s, 1, 1, %s, 0, %s, now(), now(), %s, %s, %s) RETURNING id",
            (
                owner_oid,
                status,
                Jsonb({}),
                lock_holder,
                lock_expires_at,
                str(current_turn_id) if current_turn_id else None,
            ),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _row(admin: Admin, dbname: str, proposal_id: Any) -> tuple[Any, ...]:
    with admin(dbname) as connection:
        row = connection.execute(
            "SELECT lock_holder, lock_expires_at, current_turn_id, conversation_id, revision, "
            "answers FROM proposal WHERE id = %s",
            (str(proposal_id),),
        ).fetchone()
    assert row is not None
    return tuple(row)


# --- AC1, AC5, AC9-AC12: the happy turn --------------------------------------------------------


def test_ac1_happy_turn_streams_deltas_then_done_and_fills_the_draft(
    happy_client: tuple[TestClient, StubAgentGateway],
) -> None:
    client, _stub = happy_client
    created = _create_and_lock(client)

    response = client.post(
        f"/api/proposals/{created['id']}/chat",
        json={"message": "Her name is Ally."},
        headers=AS_AGENT_A,
    )

    assert response.status_code == 200
    events = _events(response)
    assert [event for event, _ in events[:-1]] == ["delta", "delta"]
    assert events[-1][0] == "done"
    assert "revision" in events[-1][1]

    draft = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A).json()
    assert draft["answers"]["C1"] == "Ally"  # AC12: the stub's scripted patch_draft landed
    assert draft["lock"]["holder"] == "you"  # AC1: lock is back with the initiating session


def test_ac13_traceparent_propagates_to_the_gateway(
    happy_client: tuple[TestClient, StubAgentGateway],
) -> None:
    client, stub = happy_client
    created = _create_and_lock(client)

    client.post(
        f"/api/proposals/{created['id']}/chat",
        json={"message": "hi"},
        headers=AS_AGENT_A,
    )

    # Telemetry is off in this test app (no connection string), so no span is ever recording and
    # propagate.inject() has nothing to inject -- proving the seam exists and is wired without
    # needing a real exporter (Story 4.5, AC13).
    assert stub.received_traceparents == [None]


# --- AC6: non-owner or unknown proposal ---------------------------------------------------------


def test_ac6_another_agents_proposal_is_404_no_turn_starts(
    happy_client: tuple[TestClient, StubAgentGateway],
) -> None:
    client, _stub = happy_client
    created = _create_and_lock(client)

    response = client.post(
        f"/api/proposals/{created['id']}/chat",
        json={"message": "hi"},
        headers=AS_AGENT_B,
    )

    assert response.status_code == 404


def test_ac6_unknown_proposal_is_404(
    happy_client: tuple[TestClient, StubAgentGateway],
) -> None:
    client, _stub = happy_client

    response = client.post(
        f"/api/proposals/{uuid4()}/chat", json={"message": "hi"}, headers=AS_AGENT_A
    )

    assert response.status_code == 404


def test_ac6_a_submitted_proposal_is_409_proposal_submitted(
    happy_client: tuple[TestClient, StubAgentGateway], admin: Admin, migrated_db: str
) -> None:
    client, _stub = happy_client
    proposal_id = _insert_draft(
        admin, migrated_db, owner_oid=_owner_a_oid(), status="draft"
    )
    with admin(migrated_db) as connection:
        connection.execute(
            "UPDATE proposal SET status = 'submitted', submitted_at = now() WHERE id = %s",
            (str(proposal_id),),
        )

    response = client.post(
        f"/api/proposals/{proposal_id}/chat", json={"message": "hi"}, headers=AS_AGENT_A
    )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "proposal_submitted"


# --- AC7: a turn already running -----------------------------------------------------------------


def test_ac7_a_turn_already_running_is_409_turn_in_progress(
    happy_client: tuple[TestClient, StubAgentGateway], admin: Admin, migrated_db: str
) -> None:
    client, _stub = happy_client
    proposal_id = _insert_draft(
        admin,
        migrated_db,
        owner_oid=_owner_a_oid(),
        lock_holder="ai",
        lock_expires_at="2099-01-01T00:00:00+00:00",
        current_turn_id=uuid4(),
    )

    response = client.post(
        f"/api/proposals/{proposal_id}/chat", json={"message": "hi"}, headers=AS_AGENT_A
    )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "turn_in_progress"


def _owner_a_oid() -> str:
    return TEST_PRINCIPALS["agent-a"].oid


# --- AC8: no lock ---------------------------------------------------------------------------------


def test_ac8_no_lock_is_409_lock_not_held(
    happy_client: tuple[TestClient, StubAgentGateway],
) -> None:
    client, _stub = happy_client
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()  # never locked

    response = client.post(
        f"/api/proposals/{created['id']}/chat",
        json={"message": "hi"},
        headers=AS_AGENT_A,
    )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "lock_not_held"


def test_ac8_another_sessions_tab_without_the_lock_is_409(
    happy_client: tuple[TestClient, StubAgentGateway],
) -> None:
    client, _stub = happy_client
    created = _create_and_lock(client)  # SESSION_A holds it

    response = client.post(
        f"/api/proposals/{created['id']}/chat",
        json={"message": "hi"},
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_B},
    )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "lock_not_held"


# --- Mid-stream failure / timeout: answers before the failure stay, lock releases -----------------


def test_mid_stream_failure_keeps_prior_writes_and_releases_the_lock(
    db_settings: Settings, migrated_db: str, clock: FakeClock
) -> None:
    script = [
        DeltaStep("Working on it..."),
        PatchStep({"C1": "Ally"}),
        FailStep("timeout", "The agent timed out."),
    ]
    client_gen = _make_client(db_settings, migrated_db, clock, script)
    client, _stub = next(client_gen)
    try:
        created = _create_and_lock(client)

        response = client.post(
            f"/api/proposals/{created['id']}/chat",
            json={"message": "hi"},
            headers=AS_AGENT_A,
        )

        events = _events(response)
        assert events[-1][0] == "error"
        assert events[-1][1]["code"] == "timeout"

        draft = client.get(
            f"/api/proposals/{created['id']}", headers=AS_AGENT_A
        ).json()
        assert draft["answers"]["C1"] == "Ally"  # written before the failure: stays
        assert draft["lock"]["holder"] == "you"  # released all the same
    finally:
        client_gen.close()


# --- Story 4.8: a stalled gateway (cut-off) times out the same way a raised failure does --------


def test_story_4_8_a_stalled_stream_times_out_and_releases_the_lock(
    db_settings: Settings, migrated_db: str, clock: FakeClock
) -> None:
    """A gateway that goes quiet without ever raising or yielding again is still a cut-off
    (Story 4.8): ``run_chat_turn``'s own bounded wait (``stream_chunk_timeout``) ends the turn the
    same way a real ``GatewayError`` would -- one SSE ``error`` event, lock released, and whatever
    was already written stays saved. A tiny override proves it without waiting out a
    production-sized timeout (spec Boundaries: this bounds real wall-clock waiting for the next
    chunk, not a Clock-timed window, so the seam to move here is the parameter, not the FakeClock,
    coding-style.md rule 23)."""
    settings = _settings(db_settings, migrated_db)
    engine = create_engine(settings, build_password_source(settings, clock))
    install_scope(engine)
    store = SqlProposalStore(engine)
    stub = StubAgentGateway(
        engine=engine,
        signing_key=settings.turn_token_signing_key,
        clock=clock,
        script=[
            DeltaStep("Working on it..."),
            PatchStep({"C1": "Ally"}),
            HangStep(seconds=5.0),
        ],
    )

    async def scenario() -> list[Any]:
        with scoped(for_owner(_owner_a_oid())):
            proposal = await create_draft(store, _owner_a_oid(), clock)
            await store.acquire_lock(
                proposal.id, SESSION_A, clock.now(), clock.now() + LOCK_DURATION, False
            )
            proposal, token = await open_chat_turn(
                store=store,
                proposal_id=proposal.id,
                principal_oid=_owner_a_oid(),
                session_id=SESSION_A,
                signing_key=settings.turn_token_signing_key,
                clock=clock,
            )

        events = [
            event
            async for event in run_chat_turn(
                store=store,
                gateway=stub,
                proposal=proposal,
                token=token,
                session_id=SESSION_A,
                message="hi",
                clock=clock,
                traceparent=None,
                stream_chunk_timeout=timedelta(seconds=0.05),
            )
        ]
        with scoped(for_owner(_owner_a_oid())):
            after = await store.get(proposal.id)
        return [events, after]

    events, after = asyncio.run(scenario())

    assert events[-1].event == "error"
    assert events[-1].data["code"] == "timeout"
    assert after is not None
    assert after.lock_holder == SESSION_A  # released, not stuck on ai
    assert after.current_turn_id is None
    assert after.answers["C1"]["value"] == "Ally"  # written before the cut-off: stays


# --- Story 4.8: a client disconnect mid-stream still releases the lock ---------------------------


def test_story_4_8_a_client_disconnect_mid_stream_still_releases_the_lock(
    db_settings: Settings, migrated_db: str, clock: FakeClock
) -> None:
    """A browser dropping the connection mid-reply (Story 4.8): Starlette closes the SSE body
    iterator, which raises ``GeneratorExit`` into ``run_chat_turn`` at whichever ``yield`` it's
    suspended on -- never caught by ``except Exception`` (neither ``GeneratorExit`` nor a real
    disconnect's ``CancelledError`` is one). Only the ``finally`` this story adds runs regardless,
    so the lock still comes back to the session that started the turn (AD-16) instead of staying
    stuck on ``ai`` until the 5-minute safety expiry."""
    settings = _settings(db_settings, migrated_db)
    engine = create_engine(settings, build_password_source(settings, clock))
    install_scope(engine)
    store = SqlProposalStore(engine)
    stub = StubAgentGateway(
        engine=engine,
        signing_key=settings.turn_token_signing_key,
        clock=clock,
        script=[DeltaStep("Working on it..."), DeltaStep("more...")],
    )

    async def scenario() -> Any:
        with scoped(for_owner(_owner_a_oid())):
            proposal = await create_draft(store, _owner_a_oid(), clock)
            await store.acquire_lock(
                proposal.id, SESSION_A, clock.now(), clock.now() + LOCK_DURATION, False
            )
            proposal, token = await open_chat_turn(
                store=store,
                proposal_id=proposal.id,
                principal_oid=_owner_a_oid(),
                session_id=SESSION_A,
                signing_key=settings.turn_token_signing_key,
                clock=clock,
            )

        events = run_chat_turn(
            store=store,
            gateway=stub,
            proposal=proposal,
            token=token,
            session_id=SESSION_A,
            message="hi",
            clock=clock,
            traceparent=None,
        )
        first = await events.__anext__()
        assert first.event == "delta"
        # The browser drops the connection mid-reply: Starlette closes the body iterator, exactly
        # like this generator being closed while still suspended at its own yield.
        await events.aclose()

        with scoped(for_owner(_owner_a_oid())):
            return await store.get(proposal.id)

    after = asyncio.run(scenario())

    assert after is not None
    assert after.lock_holder == SESSION_A  # released, not stuck on ai
    assert after.current_turn_id is None


# --- Story 4.8, AD-16: the 5-minute safety expiry frees a lock api never got to release ----------


def test_story_4_8_the_5_minute_safety_expiry_frees_the_lock_on_the_next_check(
    happy_client: tuple[TestClient, StubAgentGateway],
    clock: FakeClock,
    admin: Admin,
    migrated_db: str,
) -> None:
    """Stands in for `api` itself crashing mid-turn (Story 4.8, AD-16): no live handler ever runs
    ``run_chat_turn``'s own lock release, so only the passage of time -- the injectable Clock,
    AD-18 -- frees it, checked the next time anyone tries to acquire the lock."""
    client, _stub = happy_client
    proposal_id = _insert_draft(
        admin,
        migrated_db,
        owner_oid=_owner_a_oid(),
        lock_holder="ai",
        lock_expires_at=(clock.now() + AI_TURN_SAFETY_WINDOW).isoformat(),
        current_turn_id=uuid4(),
    )

    still_running = client.post(
        f"/api/proposals/{proposal_id}/lock",
        json={"take_over": False},
        headers=AS_AGENT_A,
    )
    assert still_running.json()["holder"] == "ai"  # within the 5-minute window: still "running"

    # _turn_running's own expiry check is inclusive (lock_expires_at >= now, domain/proposals.py),
    # so advance one second past it, not exactly to it, to land unambiguously outside the window.
    clock.advance(AI_TURN_SAFETY_WINDOW + timedelta(seconds=1))  # api "crashed"

    response = client.post(
        f"/api/proposals/{proposal_id}/lock",
        json={"take_over": False},
        headers=AS_AGENT_A,
    )

    assert response.json()["holder"] == "you"
    _lock_holder, _expires, current_turn_id, *_rest = _row(admin, migrated_db, proposal_id)
    assert current_turn_id is None


# --- AC9: first turn creates the conversation; a race's loser reuses the winner's --------------


def test_ac9_first_turn_creates_a_conversation_and_later_turns_reuse_it(
    happy_client: tuple[TestClient, StubAgentGateway],
    admin: Admin,
    migrated_db: str,
) -> None:
    client, _stub = happy_client
    created = _create_and_lock(client)

    client.post(
        f"/api/proposals/{created['id']}/chat", json={"message": "one"}, headers=AS_AGENT_A
    )
    _lh, _le, _tid, conversation_after_first, *_rest = _row(
        admin, migrated_db, created["id"]
    )
    assert conversation_after_first is not None

    client.post(
        f"/api/proposals/{created['id']}/chat", json={"message": "two"}, headers=AS_AGENT_A
    )
    _lh, _le, _tid, conversation_after_second, *_rest = _row(
        admin, migrated_db, created["id"]
    )

    assert conversation_after_second == conversation_after_first  # reused, not recreated


def test_ac9_ensure_conversation_race_the_loser_reuses_the_winners(
    happy_client: tuple[TestClient, StubAgentGateway],
) -> None:
    client, stub = happy_client
    created = _create_and_lock(client)
    store = stub.store
    proposal_id = UUID(created["id"])

    async def race() -> tuple[str, str]:
        # A direct store call outside any REST request: scoped to the proposal's own owner, same
        # as production's chat adapter would (AD-17, security.md rule 37). Both branches race for
        # the same proposal, so both use the same owner scope.
        with scoped(for_owner(_owner_a_oid())):
            first, second = await asyncio.gather(
                store.ensure_conversation(proposal_id, "conversation-one"),
                store.ensure_conversation(proposal_id, "conversation-two"),
            )
        return first, second

    first, second = asyncio.run(race())

    assert first == second
    assert first in ("conversation-one", "conversation-two")
    stored = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A)
    assert stored.status_code == 200


# --- AC2 / security.md rule 36: next lock acquire clears a stale current_turn_id -----------------


def test_next_lock_acquire_clears_a_stale_current_turn_id(
    happy_client: tuple[TestClient, StubAgentGateway], admin: Admin, migrated_db: str
) -> None:
    client, _stub = happy_client
    proposal_id = _insert_draft(
        admin,
        migrated_db,
        owner_oid=_owner_a_oid(),
        lock_holder="ai",
        # Already past its 5-minute safety expiry: free for a plain acquire.
        lock_expires_at="2000-01-01T00:00:00+00:00",
        current_turn_id=uuid4(),
    )

    response = client.post(
        f"/api/proposals/{proposal_id}/lock",
        json={"take_over": False},
        headers=AS_AGENT_A,
    )

    assert response.status_code == 200
    assert response.json()["holder"] == "you"
    _lock_holder, _expires, current_turn_id, *_rest = _row(admin, migrated_db, proposal_id)
    assert current_turn_id is None


# --- GET history -----------------------------------------------------------------------------


def test_get_history_has_only_the_opening_checklist_before_the_first_turn(
    happy_client: tuple[TestClient, StubAgentGateway], admin: Admin, migrated_db: str
) -> None:
    """Story 4.6, AD-9: the opening checklist is always there, even with no chat yet -- but
    reading it never touches Foundry (no conversation is created just to read it)."""
    client, _stub = happy_client
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    expected_checklist = opening_message("Alice")  # AS_AGENT_A's TEST_PRINCIPALS first_name

    response = client.get(f"/api/proposals/{created['id']}/chat", headers=AS_AGENT_A)

    assert response.status_code == 200
    assert response.json() == {
        "messages": [{"role": "assistant", "text": expected_checklist}]
    }
    _lh, _le, _tid, conversation_id, *_rest = _row(admin, migrated_db, created["id"])
    assert conversation_id is None  # no Foundry side effect from reading the checklist


def test_get_history_returns_the_checklist_then_the_conversation_after_a_turn(
    happy_client: tuple[TestClient, StubAgentGateway],
) -> None:
    client, _stub = happy_client
    created = _create_and_lock(client)
    client.post(
        f"/api/proposals/{created['id']}/chat",
        json={"message": "hello there"},
        headers=AS_AGENT_A,
    )

    response = client.get(f"/api/proposals/{created['id']}/chat", headers=AS_AGENT_A)

    assert response.status_code == 200
    messages = response.json()["messages"]
    # Story 4.6: the checklist always stays first, ahead of the real Foundry history.
    assert messages[0]["role"] == "assistant"
    assert messages[0]["text"].startswith("Hi Alice.")
    assert {"role": "user", "text": "hello there"} in messages[1:]
    assert any(message["role"] == "assistant" for message in messages[1:])


def test_get_history_404s_for_another_agents_proposal(
    happy_client: tuple[TestClient, StubAgentGateway],
) -> None:
    client, _stub = happy_client
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()

    response = client.get(f"/api/proposals/{created['id']}/chat", headers=AS_AGENT_B)

    assert response.status_code == 404


# --- Direct orchestration test: run_chat_turn ends the turn even on an unexpected exception -----


def test_run_chat_turn_maps_any_unexpected_gateway_exception_to_an_sse_error(
    db_settings: Settings, migrated_db: str, clock: FakeClock
) -> None:
    settings = _settings(db_settings, migrated_db)
    engine = create_engine(settings, build_password_source(settings, clock))
    # This test builds its own engine directly, not through create_app, so nothing has installed
    # the AD-17 scope hook on it yet; the test then scopes every direct store call it makes itself,
    # the same way production's per-request middleware would (AD-17, security.md rule 37).
    install_scope(engine)
    store = SqlProposalStore(engine)

    async def scenario() -> list[Any]:
        with scoped(for_owner(_owner_a_oid())):
            proposal = await create_draft(store, _owner_a_oid(), clock)
            await store.acquire_lock(
                proposal.id, SESSION_A, clock.now(), clock.now() + LOCK_DURATION, False
            )
            proposal, token = await open_chat_turn(
                store=store,
                proposal_id=proposal.id,
                principal_oid=_owner_a_oid(),
                session_id=SESSION_A,
                signing_key=settings.turn_token_signing_key,
                clock=clock,
            )

        class _BrokenGateway:
            async def get_or_create_conversation(self) -> str:
                return "synthetic-conversation"

            async def stream(self, **_: Any) -> Any:
                raise RuntimeError("boom")
                yield  # pragma: no cover -- makes this an async generator

        events = [
            event
            async for event in run_chat_turn(
                store=store,
                gateway=_BrokenGateway(),
                proposal=proposal,
                token=token,
                session_id=SESSION_A,
                message="hi",
                clock=clock,
                traceparent=None,
            )
        ]
        with scoped(for_owner(_owner_a_oid())):
            after = await store.get(proposal.id)
        return [events, after]

    events, after = asyncio.run(scenario())

    assert events[-1].event == "error"
    assert after is not None and after.lock_holder == SESSION_A  # released, not stuck on ai
