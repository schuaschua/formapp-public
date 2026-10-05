"""Story 4.8: the per-``oid`` chat-turn throttle (spine AD-9, AD-17, AD-18) -- 3 turns per ``oid``
in any rolling 10 seconds, across every proposal, with ``429 rate_limited`` and
``retry_after_seconds`` on the 4th; refused requests take no lock and aren't counted; there is no
per-proposal limit.

Against a real migrated PostgreSQL, driven through a real ``TestClient``, with the ``FakeClock``
moved by hand rather than sleeping (AD-18, coding-style.md rule 23).
"""

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from adapters.chat.stub import DeltaStep, StubAgentGateway
from adapters.db.engine import build_password_source, create_engine
from adapters.rest.app import create_app
from adapters.rest.principal import TEST_PRINCIPALS
from adapters.settings import Settings
from domain.throttle import THROTTLE_WINDOW
from tests.fakes import FakeClock
from tests.support import AS_AGENT_A, AS_AGENT_B

Admin = Callable[[str], psycopg.Connection[Any]]

SESSION_A = "test-session"  # the `client` fixture's own default X-Session-Id


def _settings(db_settings: Settings, migrated_db: str) -> Settings:
    return db_settings.model_copy(
        update={"database_name": migrated_db, "formapp_test_mode": True}
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(
    db_settings: Settings, migrated_db: str, clock: FakeClock
) -> Iterator[TestClient]:
    settings = _settings(db_settings, migrated_db)
    engine = create_engine(settings, build_password_source(settings, clock))
    # A short, one-chunk script: each turn finishes (and so releases the lock) as soon as the
    # TestClient's POST returns, so a same-proposal turn right after it never hits
    # turn_in_progress instead of the throttle this test is after.
    stub = StubAgentGateway(
        engine=engine,
        signing_key=settings.turn_token_signing_key,
        clock=clock,
        script=[DeltaStep("ok")],
    )
    with TestClient(
        create_app(settings, clock=clock, engine=engine, agent_gateway=stub),
        headers={"X-Session-Id": SESSION_A},
    ) as test_client:
        yield test_client


def _create_and_lock(client: TestClient, headers: dict[str, str]) -> str:
    created = client.post("/api/proposals", headers=headers).json()
    client.post(
        f"/api/proposals/{created['id']}/lock",
        json={"take_over": False},
        headers=headers,
    )
    return str(created["id"])


def _send(client: TestClient, proposal_id: str, headers: dict[str, str]) -> Any:
    return client.post(
        f"/api/proposals/{proposal_id}/chat",
        json={"message": "hi"},
        headers=headers,
    )


def _log_rows(admin: Admin, dbname: str, oid: str) -> int:
    with admin(dbname) as connection:
        row = connection.execute(
            "SELECT count(*) FROM chat_turn_log WHERE oid = %s", (oid,)
        ).fetchone()
    assert row is not None
    return int(row[0])


def _owner_a_oid() -> str:
    return TEST_PRINCIPALS["agent-a"].oid


def _owner_b_oid() -> str:
    return TEST_PRINCIPALS["agent-b"].oid


# --- 4th turn in a rolling 10s window: 429 with the right retry_after_seconds -------------------


def test_story_4_8_a_4th_turn_within_10s_is_429_with_the_right_retry_after(
    client: TestClient, clock: FakeClock, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _create_and_lock(client, AS_AGENT_A)
    t0 = clock.now()

    for offset in (0, 3, 6):
        clock.set(t0 + _seconds(offset))
        response = _send(client, proposal_id, AS_AGENT_A)
        assert response.status_code == 200

    clock.set(t0 + _seconds(6))  # the 4th arrives at the same instant as the 3rd
    response = _send(client, proposal_id, AS_AGENT_A)

    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "rate_limited"
    # The oldest of the 3 (t0) leaves the window at t0+10s; "now" is t0+6s -> 4s left.
    assert body["retry_after_seconds"] == 4
    assert _log_rows(admin, migrated_db, _owner_a_oid()) == 3  # the 4th never recorded

    draft = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert draft["lock"]["holder"] == "you"  # refused: no lock ever moved to ai


# --- Two agents, 3 each: neither throttled, the count is per oid --------------------------------


def test_story_4_8_two_agents_3_each_in_10s_neither_is_throttled(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_a = _create_and_lock(client, AS_AGENT_A)
    proposal_b = _create_and_lock(client, AS_AGENT_B)

    for _ in range(3):
        assert _send(client, proposal_a, AS_AGENT_A).status_code == 200
        assert _send(client, proposal_b, AS_AGENT_B).status_code == 200

    assert _log_rows(admin, migrated_db, _owner_a_oid()) == 3
    assert _log_rows(admin, migrated_db, _owner_b_oid()) == 3


# --- Refused requests are never counted toward a later check ------------------------------------


def test_story_4_8_a_refused_request_does_not_count_toward_the_next_check(
    client: TestClient, clock: FakeClock, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _create_and_lock(client, AS_AGENT_A)
    for _ in range(3):
        assert _send(client, proposal_id, AS_AGENT_A).status_code == 200

    first_refusal = _send(client, proposal_id, AS_AGENT_A)
    second_refusal = _send(client, proposal_id, AS_AGENT_A)

    assert first_refusal.status_code == second_refusal.status_code == 429
    # Same instant, same 3 real rows behind both -- an identical retry_after_seconds proves the
    # first refusal changed nothing (a miscount would move it).
    assert (
        first_refusal.json()["retry_after_seconds"]
        == second_refusal.json()["retry_after_seconds"]
    )
    assert _log_rows(admin, migrated_db, _owner_a_oid()) == 3


# --- Window slides: once the oldest of the 3 ages out, a new turn is allowed --------------------


def test_story_4_8_the_window_slides_once_the_oldest_turn_ages_out(
    client: TestClient, clock: FakeClock
) -> None:
    proposal_id = _create_and_lock(client, AS_AGENT_A)
    t0 = clock.now()

    for offset in (0, 3, 6):
        clock.set(t0 + _seconds(offset))
        assert _send(client, proposal_id, AS_AGENT_A).status_code == 200

    clock.set(t0 + _seconds(6))
    assert _send(client, proposal_id, AS_AGENT_A).status_code == 429  # still throttled

    # Past the moment the oldest (t0) leaves the rolling 10s window.
    clock.set(t0 + THROTTLE_WINDOW + _seconds(1))
    assert _send(client, proposal_id, AS_AGENT_A).status_code == 200


# --- No per-proposal limit: 3 turns across different proposals still throttle the 4th -----------


def test_story_4_8_there_is_no_per_proposal_limit_the_oid_alone_is_throttled(
    client: TestClient,
) -> None:
    proposals = [_create_and_lock(client, AS_AGENT_A) for _ in range(4)]

    for proposal_id in proposals[:3]:
        assert _send(client, proposal_id, AS_AGENT_A).status_code == 200

    response = _send(client, proposals[3], AS_AGENT_A)

    assert response.status_code == 429


def _seconds(count: int) -> timedelta:
    return timedelta(seconds=count)
